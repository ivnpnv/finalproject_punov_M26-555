import math
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valutatrade_hub.constants import (
    LOGIN_REQUIRED_MESSAGE,
    PASSWORD_SALT_BYTES,
    TRADE_BASE_CURRENCY,
)
from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import (
    RateService,
    edit_json,
    load_json,
    save_json,
    validate_amount,
    validate_currency,
    validate_password,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging


class WalletService:
    """Регистрация, авторизация и операции с портфелями через JSON-хранилище."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.settings = SettingsLoader()
        setup_logging()
        self.data_dir = Path(
            data_dir if data_dir is not None else self.settings.get("data_dir")
        )
        self.users_path = self.data_dir / self.settings.get("users_file")
        self.portfolios_path = self.data_dir / self.settings.get("portfolios_file")
        self.rate_service = RateService(self.data_dir)

    def register(self, username: str, password: str) -> User:
        """Создаёт уникального пользователя и пустой портфель."""
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        username = username.strip()
        validate_password(password)

        users = load_json(self.users_path, [])
        for record in users:
            if record["username"] == username:
                raise ValueError(f"Имя пользователя '{username}' уже занято")

        user_id = max((record["user_id"] for record in users), default=0) + 1
        user = User(
            user_id,
            username,
            "",
            secrets.token_hex(PASSWORD_SALT_BYTES),
            datetime.now(timezone.utc),
        )
        user.change_password(password)
        portfolios = load_json(self.portfolios_path, [])
        users.append(
            {
                "user_id": user.user_id,
                "username": user.username,
                "hashed_password": user.hashed_password,
                "salt": user.salt,
                "registration_date": user.registration_date.isoformat(),
            }
        )
        portfolios.append({"user_id": user.user_id, "wallets": {}})
        save_json(self.users_path, users)
        save_json(self.portfolios_path, portfolios)
        return user

    def login(self, username: str, password: str) -> User:
        """Загружает пользователя и проверяет пароль без изменения данных."""
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        username = username.strip()
        users = load_json(self.users_path, [])
        for record in users:
            if record["username"] == username:
                user = User(
                    record["user_id"],
                    record["username"],
                    record["hashed_password"],
                    record["salt"],
                    datetime.fromisoformat(record["registration_date"]),
                )
                if not isinstance(password, str) or not user.verify_password(password):
                    raise ValueError("Неверный пароль")
                return user

        raise ValueError(f"Пользователь '{username}' не найден")

    def _load_portfolio(
        self, user: User | None, portfolios: list[dict[str, Any]] | None = None
    ) -> Portfolio:
        """Собирает модель портфеля из записей хранилища."""
        if user is None:
            raise ValueError(LOGIN_REQUIRED_MESSAGE)

        if portfolios is None:
            portfolios = load_json(self.portfolios_path, [])
        for record in portfolios:
            if record["user_id"] == user.user_id:
                wallets = {}
                for currency, wallet_data in record["wallets"].items():
                    wallets[currency] = Wallet(currency, wallet_data["balance"])
                return Portfolio(user, wallets)

        raise ValueError(f"Портфель пользователя '{user.username}' не найден")

    def _save_portfolio(
        self, portfolio: Portfolio, portfolios: list[dict[str, Any]]
    ) -> None:
        """Обновляет запись портфеля в текущем цикле изменения JSON."""
        wallets = {
            code: {"balance": wallet.balance}
            for code, wallet in portfolio.wallets.items()
        }
        for record in portfolios:
            if record["user_id"] == portfolio.user.user_id:
                record["wallets"] = wallets
                return

        raise ValueError(f"Портфель пользователя '{portfolio.user.username}' не найден")

    @contextmanager
    def _edit_portfolio(self, user: User | None) -> Iterator[Portfolio]:
        """Сохраняет портфель только после успешного завершения операции."""
        with edit_json(self.portfolios_path, []) as portfolios:
            portfolio = self._load_portfolio(user, portfolios)
            yield portfolio
            self._save_portfolio(portfolio, portfolios)

    def show_portfolio(
        self, user: User | None, base_currency: str | None = None
    ) -> dict[str, Any]:
        """Возвращает балансы и итоговую оценку портфеля для CLI."""
        portfolio = self._load_portfolio(user)
        if base_currency is None:
            base_currency = self.settings.get("base_currency")
        base_currency = validate_currency(base_currency)
        self.rate_service.get_rate(base_currency, base_currency)

        rows = []
        for currency, wallet in portfolio.wallets.items():
            rate = self.rate_service.get_rate(currency, base_currency)["rate"]
            value = wallet.balance * rate
            if not math.isfinite(value):
                raise ValueError("Стоимость кошелька выходит за допустимый диапазон.")
            rows.append(
                {"currency": currency, "balance": wallet.balance, "value": value}
            )
        total = sum(row["value"] for row in rows)
        if not math.isfinite(total):
            raise ValueError("Стоимость портфеля выходит за допустимый диапазон.")

        return {
            "username": user.username,
            "base_currency": base_currency,
            "rows": rows,
            "total": total,
        }

    def get_rate(self, from_currency: str, to_currency: str) -> dict[str, float | str]:
        """Проверяет валюты и возвращает курс с отметкой времени."""
        get_currency(from_currency)
        get_currency(to_currency)
        return self.rate_service.get_rate(from_currency, to_currency)

    @log_action(verbose=True)
    def buy(self, user: User | None, currency: str, amount: float) -> dict[str, Any]:
        """Пополняет валютный кошелёк, создавая его при первой покупке."""
        return self._trade(user, currency, amount, "buy")

    @log_action(verbose=True)
    def sell(self, user: User | None, currency: str, amount: float) -> dict[str, Any]:
        """Продаёт валюту при наличии достаточного баланса."""
        return self._trade(user, currency, amount, "sell")

    def _trade(
        self, user: User | None, currency: str, amount: float, action: str
    ) -> dict[str, Any]:
        """Общий цикл проверки, оценки и сохранения покупки или продажи."""
        with self._edit_portfolio(user) as portfolio:
            currency = get_currency(currency).code
            amount = validate_amount(amount)
            if currency not in portfolio.wallets:
                if action == "sell":
                    raise InsufficientFundsError(0.0, amount, currency)
                portfolio.add_currency(currency)
            wallet = portfolio.get_wallet(currency)
            if action == "sell" and amount > wallet.balance:
                raise InsufficientFundsError(wallet.balance, amount, currency)
            rate = self.rate_service.get_rate(currency, TRADE_BASE_CURRENCY)["rate"]
            value = amount * rate
            if not math.isfinite(value):
                raise ValueError("Стоимость сделки выходит за допустимый диапазон.")
            before = wallet.balance
            if action == "buy":
                wallet.deposit(amount)
            else:
                wallet.withdraw(amount)
            return {
                "currency": currency,
                "amount": amount,
                "before": before,
                "after": wallet.balance,
                "rate": rate,
                "value": value,
            }
