import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valutatrade_hub.constants import (
    INVALID_AMOUNT_MESSAGE,
    MIN_PASSWORD_LENGTH,
    TRADE_BASE_CURRENCY,
)
from valutatrade_hub.core.currencies import (
    CURRENCIES,
    CryptoCurrency,
    get_currency,
    validate_code,
)
from valutatrade_hub.core.exceptions import RatesUnavailableError
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


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
    """Читает кэш Parser Service без сетевых запросов и изменения файлов."""

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
        self.database = DatabaseManager()

    def get_rate(self, from_currency: str, to_currency: str) -> dict[str, float | str]:
        """Вычисляет курс через USD из одного снимка; проверяет обе котировки."""
        validate_currency(from_currency)
        validate_currency(to_currency)
        now = datetime.now(timezone.utc)
        if from_currency == to_currency:
            return {"rate": 1.0, "updated_at": now.isoformat()}
        snapshot = self.database.read(self.filepath, {"pairs": {}})
        if not isinstance(snapshot, dict) or not isinstance(
            snapshot.get("pairs"), dict
        ):
            raise RatesUnavailableError(
                "Неверный формат кэша курсов. Выполните update-rates."
            )
        pairs = snapshot["pairs"]
        source = self._get_usd_rate(pairs, from_currency, now)
        target = self._get_usd_rate(pairs, to_currency, now)
        rate = source["rate"] / target["rate"]
        if not math.isfinite(rate) or rate <= 0:
            raise RatesUnavailableError("Некорректный курс. Выполните update-rates.")
        return {
            "rate": rate,
            "updated_at": min(source["updated_at"], target["updated_at"]),
        }

    def _get_usd_rate(
        self, pairs: dict[str, Any], code: str, now: datetime
    ) -> dict[str, float | str]:
        """Возвращает свежий курс к USD или выбрасывает RatesUnavailableError."""
        if code == TRADE_BASE_CURRENCY:
            return {"rate": 1.0, "updated_at": now.isoformat()}
        pair = f"{code}_{TRADE_BASE_CURRENCY}"
        cached = pairs.get(pair)
        if not self.is_fresh(cached, now):
            reason = "отсутствует" if cached is None else "устарел или некорректен"
            raise RatesUnavailableError(
                f"Курс {pair} {reason}. Выполните update-rates."
            )
        timestamp = datetime.fromisoformat(cached["updated_at"])
        return {
            "rate": float(cached["rate"]),
            "updated_at": timestamp.astimezone(timezone.utc).isoformat(),
        }

    def list_rates(
        self,
        currency: str | None = None,
        top: int | None = None,
        base: str = TRADE_BASE_CURRENCY,
    ) -> dict[str, Any]:
        """Возвращает курсы из одного снимка кэша с фильтрами и признаками свежести."""
        if top is not None and (type(top) is not int or top <= 0):
            raise ValueError("--top должен быть положительным целым числом.")
        if currency is not None:
            validate_code(currency)
        validate_currency(base)
        snapshot = self._read_rates_snapshot()
        pairs = snapshot["pairs"]
        now = datetime.now(timezone.utc)
        codes = self._select_codes(pairs, currency, top, base)
        target = self._cached_quote(pairs, base, now)
        rows = []
        warnings = []
        for code in codes:
            try:
                source = self._cached_quote(pairs, code, now)
                value = source["rate"] / target["rate"]
                if not math.isfinite(value) or value <= 0:
                    raise RatesUnavailableError(f"Некорректный курс {code}→{base}.")
                rows.append(
                    {
                        "pair": f"{code}_{base}",
                        "rate": value,
                        "updated_at": min(source["updated_at"], target["updated_at"]),
                        "fresh": self.is_fresh(source, now)
                        and self.is_fresh(target, now),
                    }
                )
            except RatesUnavailableError as error:
                if currency is not None:
                    raise
                warnings.append(str(error))
        rows.sort(key=lambda row: (-row["rate"], row["pair"]) if top else row["pair"])
        if top is not None:
            rows = rows[:top]
        return {
            "rows": rows,
            "last_refresh": snapshot.get("last_refresh"),
            "warnings": warnings,
        }

    def _read_rates_snapshot(self) -> dict[str, Any]:
        """Проверяет структуру кэша и сообщает об отсутствии котировок."""
        snapshot = self.database.read(self.filepath, {"pairs": {}})
        if snapshot == {}:
            snapshot = {"pairs": {}}
        if not isinstance(snapshot, dict) or not isinstance(
            snapshot.get("pairs"), dict
        ):
            raise RatesUnavailableError("Неверный формат кэша. Выполните update-rates.")
        pairs = snapshot["pairs"]
        if not pairs:
            raise RatesUnavailableError(
                "Локальный кеш курсов пуст. Выполните 'update-rates', "
                "чтобы загрузить данные."
            )
        return snapshot

    def _select_codes(
        self,
        pairs: dict[str, Any],
        currency: str | None,
        top: int | None,
        base: str,
    ) -> list[str]:
        """Выбирает валюты для просмотра и ограничивает top криптовалютами."""
        if currency is not None:
            if currency not in CURRENCIES or (
                currency != TRADE_BASE_CURRENCY
                and f"{currency}_{TRADE_BASE_CURRENCY}" not in pairs
            ):
                raise RatesUnavailableError(f"Курс для '{currency}' не найден в кеше.")
            codes = [currency]
        else:
            codes = sorted(
                code
                for code in CURRENCIES
                if f"{code}_{TRADE_BASE_CURRENCY}" in pairs and code != base
            )
            if base != TRADE_BASE_CURRENCY:
                codes.append(TRADE_BASE_CURRENCY)
        if top is not None:
            codes = [
                code for code in codes if isinstance(CURRENCIES[code], CryptoCurrency)
            ]
        return codes

    def _cached_quote(
        self, pairs: dict[str, Any], code: str, now: datetime
    ) -> dict[str, float | str]:
        """Читает корректную котировку независимо от TTL для просмотра кэша."""
        if code == TRADE_BASE_CURRENCY:
            return {"rate": 1.0, "updated_at": now.isoformat()}
        cached = pairs.get(f"{code}_{TRADE_BASE_CURRENCY}")
        try:
            rate = cached["rate"]
            timestamp = datetime.fromisoformat(cached["updated_at"])
            if (
                type(rate) not in (int, float)
                or not math.isfinite(rate)
                or rate <= 0
                or timestamp.tzinfo is None
                or timestamp > now
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise RatesUnavailableError(
                f"Курс для '{code}' отсутствует или некорректен. "
                "Выполните update-rates."
            ) from None
        return {
            "rate": float(rate),
            "updated_at": timestamp.astimezone(timezone.utc).isoformat(),
        }

    def is_fresh(self, cached: Any, now: datetime) -> bool:
        """Проверяет конечное значение, часовой пояс и возраст относительно TTL."""
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
            return False
        return 0 <= (now - updated_at).total_seconds() < self.ttl_seconds
