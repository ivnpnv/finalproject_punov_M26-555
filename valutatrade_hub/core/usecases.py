import math
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging


class WalletService:
    def __init__(self, data_dir=None):
        self.settings = SettingsLoader()
        setup_logging()
        self.data_dir = Path(
            data_dir if data_dir is not None else self.settings.get("data_dir")
        )
        self.users_path = self.data_dir / self.settings.get("users_file")
        self.portfolios_path = self.data_dir / self.settings.get("portfolios_file")
        self.rate_service = RateService(self.data_dir)

    def register(self, username, password):
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        username = username.strip()
        if not isinstance(password, str) or len(password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")

        users = load_json(self.users_path, [])
        for record in users:
            if record["username"] == username:
                raise ValueError(f"Имя пользователя '{username}' уже занято")

        user_id = max((record["user_id"] for record in users), default=0) + 1
        user = User(
            user_id,
            username,
            "",
            secrets.token_hex(16),
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

    def login(self, username, password):
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
        if user is None:
            raise ValueError("Сначала выполните login")

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
        with edit_json(self.portfolios_path, []) as portfolios:
            portfolio = self._load_portfolio(user, portfolios)
            yield portfolio
            self._save_portfolio(portfolio, portfolios)

    def show_portfolio(self, user, base_currency=None):
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
        total = portfolio.get_total_value(base_currency, self.rate_service)

        return {
            "username": user.username,
            "base_currency": base_currency,
            "rows": rows,
            "total": total,
        }

    def get_rate(self, from_currency: str, to_currency: str) -> dict[str, float | str]:
        get_currency(from_currency)
        get_currency(to_currency)
        return self.rate_service.get_rate(from_currency, to_currency)

    @log_action(verbose=True)
    def buy(self, user: User | None, currency: str, amount: float) -> dict[str, Any]:
        with self._edit_portfolio(user) as portfolio:
            currency = get_currency(currency).code
            amount = validate_amount(amount)
            rate = self.rate_service.get_rate(currency, "USD")["rate"]
            value = amount * rate
            if not math.isfinite(value):
                raise ValueError("Стоимость покупки выходит за допустимый диапазон.")

            if currency not in portfolio.wallets:
                portfolio.add_currency(currency)
            wallet = portfolio.get_wallet(currency)
            before = wallet.balance
            wallet.deposit(amount)
            return {
                "currency": currency,
                "amount": amount,
                "before": before,
                "after": wallet.balance,
                "rate": rate,
                "value": value,
            }

    @log_action(verbose=True)
    def sell(self, user: User | None, currency: str, amount: float) -> dict[str, Any]:
        with self._edit_portfolio(user) as portfolio:
            currency = get_currency(currency).code
            amount = validate_amount(amount)
            if currency not in portfolio.wallets:
                raise InsufficientFundsError(0.0, amount, currency)
            wallet = portfolio.get_wallet(currency)
            if amount > wallet.balance:
                raise InsufficientFundsError(wallet.balance, amount, currency)

            rate = self.rate_service.get_rate(currency, "USD")["rate"]
            value = amount * rate
            if not math.isfinite(value):
                raise ValueError("Стоимость продажи выходит за допустимый диапазон.")
            before = wallet.balance
            wallet.withdraw(amount)
            return {
                "currency": currency,
                "amount": amount,
                "before": before,
                "after": wallet.balance,
                "rate": rate,
                "value": value,
            }
