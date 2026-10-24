import math
from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError


def validate_code(code):
    if (
        not isinstance(code, str)
        or not 2 <= len(code) <= 5
        or not code.isascii()
        or not code.isalpha()
        or code != code.upper()
    ):
        raise ValueError(
            "Код валюты должен содержать от 2 до 5 заглавных латинских букв."
        )
    return code


class Currency(ABC):
    def __init__(self, name, code):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым.")
        self.name = name.strip()
        self.code = validate_code(code)

    @abstractmethod
    def get_display_info(self):
        pass


class FiatCurrency(Currency):
    def __init__(self, name, code, issuing_country):
        super().__init__(name, code)
        if not isinstance(issuing_country, str) or not issuing_country.strip():
            raise ValueError("Страна или зона эмиссии не может быть пустой.")
        self.issuing_country = issuing_country.strip()

    def get_display_info(self):
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    def __init__(self, name, code, algorithm, market_cap):
        super().__init__(name, code)
        if not isinstance(algorithm, str) or not algorithm.strip():
            raise ValueError("Алгоритм не может быть пустым.")
        if type(market_cap) not in (int, float):
            raise ValueError("Капитализация должна быть числом.")
        if not math.isfinite(market_cap) or market_cap < 0:
            raise ValueError(
                "Капитализация должна быть конечным неотрицательным числом."
            )
        self.algorithm = algorithm.strip()
        self.market_cap = float(market_cap)

    def get_display_info(self):
        market_cap = f"{self.market_cap:.2e}".replace("e+", "e")
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {market_cap})"
        )


CURRENCIES = {
    "USD": FiatCurrency("US Dollar", "USD", "United States"),
    "EUR": FiatCurrency("Euro", "EUR", "Eurozone"),
    "RUB": FiatCurrency("Russian Ruble", "RUB", "Russia"),
    "BTC": CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
    "ETH": CryptoCurrency("Ethereum", "ETH", "Ethash", 0.0),
}


def get_currency(code):
    validate_code(code)
    if code not in CURRENCIES:
        raise CurrencyNotFoundError(code)
    return CURRENCIES[code]
