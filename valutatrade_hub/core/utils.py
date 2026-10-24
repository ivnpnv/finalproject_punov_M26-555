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

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import SettingsLoader

_json_lock = RLock()


def load_json(filepath, default):
    try:
        with open(filepath, encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return deepcopy(default)
    except json.JSONDecodeError:
        raise ValueError(f"Не удалось прочитать JSON-файл: {filepath}.") from None


def save_json(filepath: str | Path, data: Any) -> None:
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
                json.dump(data, file, ensure_ascii=False, indent=4, allow_nan=False)
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


def validate_currency(code):
    return get_currency(code).code


def validate_amount(amount):
    if type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0:
        raise ValueError("'amount' должен быть положительным числом")
    return float(amount)


class RateService:
    def __init__(self, data_dir=None, ttl_seconds=None):
        settings = SettingsLoader()
        data_dir = data_dir if data_dir is not None else settings.get("data_dir")
        self.filepath = Path(data_dir) / settings.get("rates_file")
        self.ttl_seconds = (
            ttl_seconds
            if ttl_seconds is not None
            else settings.get("rates_ttl_seconds")
        )
        self.exchange_rates = {
            "USD": 1.0,
            "EUR": 1.0786,
            "BTC": 59337.21,
            "RUB": 0.01016,
            "ETH": 3720.0,
        }

    def get_rate(self, from_currency, to_currency):
        validate_currency(from_currency)
        validate_currency(to_currency)
        with edit_json(self.filepath, {}) as rates:
            if not isinstance(rates, dict):
                raise ValueError("Файл rates.json должен содержать словарь курсов.")

            key = f"{from_currency}_{to_currency}"
            now = datetime.now(timezone.utc)
            cached = rates.get(key)

            same_currency = from_currency == to_currency
            if self.is_fresh(cached, now) and (
                not same_currency or cached["rate"] == 1
            ):
                return {
                    "rate": float(cached["rate"]),
                    "updated_at": cached["updated_at"],
                }

            try:
                rate = (
                    1.0
                    if same_currency
                    else self.exchange_rates[from_currency]
                    / self.exchange_rates[to_currency]
                )
            except (KeyError, ZeroDivisionError, TypeError):
                raise ApiRequestError(
                    f"не удалось получить курс {from_currency}→{to_currency}"
                ) from None
            if not math.isfinite(rate) or rate <= 0:
                raise ApiRequestError("источник вернул некорректный курс")
            result = {"rate": rate, "updated_at": now.isoformat()}
            rates[key] = result
            rates["source"] = "StaticRates"
            rates["last_refresh"] = result["updated_at"]
            return result

    def is_fresh(self, cached, now):
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
