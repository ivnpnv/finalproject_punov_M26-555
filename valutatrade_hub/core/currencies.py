import math
from abc import ABC, abstractmethod

from valutatrade_hub.constants import (
    MARKET_CAP_FORMAT,
    MAX_CURRENCY_CODE_LENGTH,
    MIN_CURRENCY_CODE_LENGTH,
)
from valutatrade_hub.core.exceptions import CurrencyNotFoundError


def validate_code(code: str) -> str:
    """Проверяет формат кода независимо от присутствия валюты в реестре."""
    if (
        not isinstance(code, str)
        or not MIN_CURRENCY_CODE_LENGTH <= len(code) <= MAX_CURRENCY_CODE_LENGTH
        or not code.isascii()
        or not code.isalpha()
        or code != code.upper()
    ):
        raise ValueError(
            f"Код валюты должен содержать от {MIN_CURRENCY_CODE_LENGTH} "
            f"до {MAX_CURRENCY_CODE_LENGTH} заглавных латинских букв."
        )
    return code


class Currency(ABC):
    """Общий интерфейс валюты с проверкой имени и кода."""

    def __init__(self, name: str, code: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым.")
        self.name = name.strip()
        self.code = validate_code(code)

    @abstractmethod
    def get_display_info(self) -> str:
        """Возвращает описание валюты для интерфейса и логов."""
        pass


class FiatCurrency(Currency):
    """Фиатная валюта со страной или зоной эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        super().__init__(name, code)
        if not isinstance(issuing_country, str) or not issuing_country.strip():
            raise ValueError("Страна или зона эмиссии не может быть пустой.")
        self.issuing_country = issuing_country.strip()

    def get_display_info(self) -> str:
        """Возвращает код, название и зону эмиссии."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и последней известной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float) -> None:
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

    def get_display_info(self) -> str:
        """Возвращает код, название, алгоритм и краткую капитализацию."""
        market_cap = format(self.market_cap, MARKET_CAP_FORMAT).replace("e+", "e")
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {market_cap})"
        )


CURRENCIES = {
    "USD": FiatCurrency("US Dollar", "USD", "United States"),
    "EUR": FiatCurrency("Euro", "EUR", "Eurozone"),
    "GBP": FiatCurrency("Pound Sterling", "GBP", "United Kingdom"),
    "RUB": FiatCurrency("Russian Ruble", "RUB", "Russia"),
    "BTC": CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
    "SOL": CryptoCurrency("Solana", "SOL", "Proof of Stake", 0.0),
    "ETH": CryptoCurrency("Ethereum", "ETH", "Ethash", 0.0),
}


def get_currency(code: str) -> Currency:
    """Возвращает зарегистрированную валюту или CurrencyNotFoundError."""
    validate_code(code)
    if code not in CURRENCIES:
        raise CurrencyNotFoundError(code)
    return CURRENCIES[code]
