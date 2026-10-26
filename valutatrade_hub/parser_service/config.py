"""Настройки источников и путей Parser Service."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.core.currencies import validate_code
from valutatrade_hub.infra.settings import SettingsLoader

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"
FIAT_CURRENCIES = ("EUR", "GBP", "RUB")
CRYPTO_CURRENCIES = ("BTC", "ETH", "SOL")
CRYPTO_ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
REQUEST_TIMEOUT = 10
UPDATE_INTERVAL_SECONDS = 300


def _data_path(setting: str) -> Path:
    """Получает путь из общей конфигурации приложения."""
    settings = SettingsLoader()
    return Path(settings.get("data_dir")) / settings.get(setting)


@dataclass
class ParserConfig:
    """Загружает ключи при создании; исключает секреты из repr."""

    exchangerate_api_key: str = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY", ""), repr=False
    )
    coingecko_api_key: str = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY", ""), repr=False
    )
    coingecko_url: str = COINGECKO_URL
    exchangerate_api_url: str = EXCHANGERATE_API_URL
    base_currency: str = "USD"
    fiat_currencies: tuple[str, ...] = FIAT_CURRENCIES
    crypto_currencies: tuple[str, ...] = CRYPTO_CURRENCIES
    crypto_id_map: dict[str, str] = field(default_factory=lambda: CRYPTO_ID_MAP.copy())
    rates_file_path: Path = field(default_factory=lambda: _data_path("rates_file"))
    history_file_path: Path = field(default_factory=lambda: _data_path("history_file"))
    request_timeout: float = REQUEST_TIMEOUT
    update_interval: float = UPDATE_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        """Проверяет настройки до первого запроса к API."""
        for value in (self.request_timeout, self.update_interval):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("Таймаут и интервал должны быть положительными.")
        validate_code(self.base_currency)
        for code in (*self.fiat_currencies, *self.crypto_currencies):
            validate_code(code)
        if any(not self.crypto_id_map.get(code) for code in self.crypto_currencies):
            raise ValueError("Для каждой криптовалюты нужен ID CoinGecko.")
        self.rates_file_path = Path(self.rates_file_path)
        self.history_file_path = Path(self.history_file_path)
        if self.rates_file_path.resolve() == self.history_file_path.resolve():
            raise ValueError("История и кэш должны храниться в разных файлах.")
