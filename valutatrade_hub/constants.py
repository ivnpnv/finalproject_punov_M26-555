"""Общие ограничения, форматы и настройки по умолчанию."""

MIN_PASSWORD_LENGTH = 4
PASSWORD_SALT_BYTES = 16
MIN_CURRENCY_CODE_LENGTH = 2
MAX_CURRENCY_CODE_LENGTH = 5
JSON_INDENT = 4
TRADE_BASE_CURRENCY = "USD"
ACTION_LOGGER_NAME = "valutatrade.actions"
PARSER_LOGGER_NAME = "valutatrade.parser"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
AMOUNT_FORMAT = ".4f"
PRICE_FORMAT = ".2f"
MONEY_FORMAT = ",.2f"
RATE_FORMAT = ".8f"
MARKET_CAP_FORMAT = ".2e"
LOGIN_REQUIRED_MESSAGE = "Сначала выполните login"
INVALID_AMOUNT_MESSAGE = "'amount' должен быть положительным числом"
DEFAULT_SETTINGS = {
    "data_dir": "data",
    "users_file": "users.json",
    "portfolios_file": "portfolios.json",
    "rates_file": "rates.json",
    "history_file": "exchange_rates.json",
    "rates_ttl_seconds": 300,
    "base_currency": TRADE_BASE_CURRENCY,
    "log_file": "logs/actions.log",
    "parser_log_file": "logs/parser.log",
    "log_format": "%(levelname)s %(asctime)s %(message)s",
    "log_level": "INFO",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 3,
}
