import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


def load_json(filepath, default):
    try:
        with open(filepath, encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return deepcopy(default)
    except json.JSONDecodeError:
        raise ValueError(f"Не удалось прочитать JSON-файл: {filepath}.") from None


def save_json(filepath, data):
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def validate_currency(code):
    if (
        not isinstance(code, str)
        or not code
        or not code.isascii()
        or not code.isalpha()
        or code != code.upper()
    ):
        raise ValueError("Код валюты должен состоять из заглавных латинских букв.")
    return code


def validate_amount(amount):
    if (
        type(amount) not in (int, float)
        or not math.isfinite(amount)
        or amount <= 0
    ):
        raise ValueError("'amount' должен быть положительным числом")
    return float(amount)


class RateService:
    def __init__(self, data_dir="data", ttl_seconds=300):
        self.filepath = Path(data_dir) / "rates.json"
        self.ttl_seconds = ttl_seconds
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
        rates = load_json(self.filepath, {})
        if not isinstance(rates, dict):
            raise ValueError("Файл rates.json должен содержать словарь курсов.")

        key = f"{from_currency}_{to_currency}"
        now = datetime.now(timezone.utc)
        cached = rates.get(key)

        same_currency = from_currency == to_currency
        if same_currency and from_currency not in self.exchange_rates:
            raise ValueError(
                f"Курс {from_currency}→{to_currency} недоступен. "
                "Повторите попытку позже."
            )

        if self.is_fresh(cached, now) and (not same_currency or cached["rate"] == 1):
            return {"rate": float(cached["rate"]), "updated_at": cached["updated_at"]}

        if (
            from_currency not in self.exchange_rates
            or to_currency not in self.exchange_rates
        ):
            raise ValueError(
                f"Курс {from_currency}→{to_currency} недоступен. "
                "Повторите попытку позже."
            )

        rate = self.exchange_rates[from_currency] / self.exchange_rates[to_currency]
        result = {"rate": rate, "updated_at": now.isoformat()}
        rates[key] = result
        rates["source"] = "StaticRates"
        rates["last_refresh"] = result["updated_at"]
        save_json(self.filepath, rates)
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
