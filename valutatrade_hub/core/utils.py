import json
import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

from valutatrade_hub.constants import (
    INVALID_AMOUNT_MESSAGE,
    JSON_INDENT,
    MIN_PASSWORD_LENGTH,
    STATIC_USD_RATES,
    TRADE_BASE_CURRENCY,
)
from valutatrade_hub.core.currencies import CURRENCIES, get_currency
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import SettingsLoader

_json_lock = RLock()


def load_json(filepath: str | Path, default: Any) -> Any:
    """Читает JSON; для отсутствующего файла возвращает независимый default."""
    try:
        with open(filepath, encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return deepcopy(default)
    except json.JSONDecodeError:
        raise ValueError(f"Не удалось прочитать JSON-файл: {filepath}.") from None


def save_json(filepath: str | Path, data: Any) -> None:
    """Атомарно заменяет JSON, сохраняя старый файл при ошибке записи."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with _json_lock:
        temporary_path = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=filepath.parent,
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                json.dump(
                    data,
                    file,
                    ensure_ascii=False,
                    indent=JSON_INDENT,
                    allow_nan=False,
                )
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(filepath)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


@contextmanager
def edit_json(filepath: str | Path, default: Any) -> Iterator[Any]:
    """Сохраняет изменения после успешного блока, блокируя потоки процесса."""
    with _json_lock:
        data = load_json(filepath, default)
        original = deepcopy(data)
        yield data
        if data != original:
            save_json(filepath, data)


def validate_currency(code: str) -> str:
    """Возвращает код зарегистрированной валюты или выбрасывает исключение."""
    return get_currency(code).code


def validate_amount(amount: float) -> float:
    """Проверяет конечную положительную сумму, отклоняя bool."""
    if type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0:
        raise ValueError(INVALID_AMOUNT_MESSAGE)
    return float(amount)


def validate_password(password: str) -> str:
    """Проверяет тип и минимальную длину пароля."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    return password


class RateService:
    """Хранит только курсы к USD; остальные пары вычисляет из них."""

    def __init__(
        self, data_dir: str | Path | None = None, ttl_seconds: float | None = None
    ) -> None:
        settings = SettingsLoader()
        data_dir = data_dir if data_dir is not None else settings.get("data_dir")
        self.filepath = Path(data_dir) / settings.get("rates_file")
        self.ttl_seconds = (
            ttl_seconds
            if ttl_seconds is not None
            else settings.get("rates_ttl_seconds")
        )
        if (
            type(self.ttl_seconds) not in (int, float)
            or not math.isfinite(self.ttl_seconds)
            or self.ttl_seconds < 0
        ):
            raise ValueError("TTL курсов должен быть конечным неотрицательным числом.")
        self.exchange_rates = STATIC_USD_RATES.copy()

    def get_rate(self, from_currency: str, to_currency: str) -> dict[str, float | str]:
        """Возвращает курс и время самой старой из использованных котировок."""
        validate_currency(from_currency)
        validate_currency(to_currency)
        now = datetime.now(timezone.utc)
        if from_currency == to_currency:
            return {"rate": 1.0, "updated_at": now.isoformat()}

        with edit_json(self.filepath, {}) as rates:
            if not isinstance(rates, dict):
                raise ValueError("Файл rates.json должен содержать словарь курсов.")
            self._prune_cache(rates, now)
            source = self._get_usd_rate(rates, from_currency, now)
            target = self._get_usd_rate(rates, to_currency, now)
            rate = source["rate"] / target["rate"]
            if not math.isfinite(rate) or rate <= 0:
                raise ApiRequestError("источник вернул некорректный курс")
            updated_at = min(source["updated_at"], target["updated_at"])
            return {"rate": rate, "updated_at": updated_at}

    def _prune_cache(self, rates: dict, now: datetime) -> None:
        """Удаляет устаревшие и производные пары; размер ограничен реестром."""
        allowed = {f"{code}_{TRADE_BASE_CURRENCY}" for code in CURRENCIES}
        metadata = {"source", "last_refresh"}
        for key in list(rates):
            if key not in metadata and (
                key not in allowed or not self.is_fresh(rates[key], now)
            ):
                del rates[key]

    def _get_usd_rate(
        self, rates: dict, code: str, now: datetime
    ) -> dict[str, float | str]:
        """Берёт котировку к USD из кэша или обновляет через заглушку."""
        if code == TRADE_BASE_CURRENCY:
            return {"rate": 1.0, "updated_at": now.isoformat()}
        key = f"{code}_{TRADE_BASE_CURRENCY}"
        cached = rates.get(key)
        if self.is_fresh(cached, now):
            timestamp = datetime.fromisoformat(cached["updated_at"])
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return {
                "rate": float(cached["rate"]),
                "updated_at": timestamp.astimezone(timezone.utc).isoformat(),
            }
        rate = self.exchange_rates.get(code)
        if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
            raise ApiRequestError(
                f"не удалось получить курс {code}→{TRADE_BASE_CURRENCY}"
            )
        result = {"rate": float(rate), "updated_at": now.isoformat()}
        rates[key] = result
        rates["source"] = "StaticRates"
        rates["last_refresh"] = result["updated_at"]
        return result

    def is_fresh(self, cached: Any, now: datetime) -> bool:
        """Проверяет значение и возраст котировки с учётом TTL."""
        if not isinstance(cached, dict):
            return False

        rate = cached.get("rate")
        if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
            return False

        try:
            updated_at = datetime.fromisoformat(cached["updated_at"])
        except (KeyError, TypeError, ValueError):
            return False

        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        age = (now - updated_at).total_seconds()
        return 0 <= age < self.ttl_seconds
