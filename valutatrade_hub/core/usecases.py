import math
import secrets
from datetime import datetime, timezone
from pathlib import Path

from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import (
    RateService,
    load_json,
    save_json,
    validate_amount,
    validate_currency,
)


class WalletService:
    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.rate_service = RateService(self.data_dir)

    def register(self, username, password):
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        username = username.strip()
        if not isinstance(password, str) or len(password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")

        users = load_json(self.data_dir / "users.json", [])
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
        portfolios = load_json(self.data_dir / "portfolios.json", [])
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
        save_json(self.data_dir / "users.json", users)
        save_json(self.data_dir / "portfolios.json", portfolios)
        return user

    def login(self, username, password):
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        username = username.strip()
        users = load_json(self.data_dir / "users.json", [])
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

    def _load_portfolio(self, user):
        if user is None:
            raise ValueError("Сначала выполните login")

        portfolios = load_json(self.data_dir / "portfolios.json", [])
        for record in portfolios:
            if record["user_id"] == user.user_id:
                wallets = {}
                for currency, wallet_data in record["wallets"].items():
                    wallets[currency] = Wallet(currency, wallet_data["balance"])
                return Portfolio(user, wallets)

        raise ValueError(f"Портфель пользователя '{user.username}' не найден")

    def _save_portfolio(self, portfolio):
        portfolios = load_json(self.data_dir / "portfolios.json", [])
        wallets = {
            code: {"balance": wallet.balance}
            for code, wallet in portfolio.wallets.items()
        }
        for record in portfolios:
            if record["user_id"] == portfolio.user.user_id:
                record["wallets"] = wallets
                save_json(self.data_dir / "portfolios.json", portfolios)
                return

        raise ValueError(f"Портфель пользователя '{portfolio.user.username}' не найден")

    def show_portfolio(self, user, base_currency="USD"):
        portfolio = self._load_portfolio(user)
        base_currency = validate_currency(base_currency)
        try:
            self.rate_service.get_rate(base_currency, base_currency)
        except ValueError:
            raise ValueError(
                f"Неизвестная базовая валюта '{base_currency}'"
            ) from None

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

    def get_rate(self, from_currency, to_currency):
        return self.rate_service.get_rate(from_currency, to_currency)

    def buy(self, user, currency, amount):
        portfolio = self._load_portfolio(user)
        currency = validate_currency(currency)
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
        self._save_portfolio(portfolio)
        return {
            "currency": currency,
            "amount": amount,
            "before": before,
            "after": wallet.balance,
            "rate": rate,
            "value": value,
        }

    def sell(self, user, currency, amount):
        portfolio = self._load_portfolio(user)
        currency = validate_currency(currency)
        amount = validate_amount(amount)
        if currency not in portfolio.wallets:
            raise ValueError(
                f"У вас нет кошелька '{currency}'. "
                "Он создаётся автоматически при первой покупке."
            )
        wallet = portfolio.get_wallet(currency)
        if amount > wallet.balance:
            raise ValueError(
                f"Недостаточно средств: доступно {wallet.balance:.4f} {currency}, "
                f"требуется {amount:.4f} {currency}"
            )

        rate = self.rate_service.get_rate(currency, "USD")["rate"]
        value = amount * rate
        if not math.isfinite(value):
            raise ValueError("Стоимость продажи выходит за допустимый диапазон.")
        before = wallet.balance
        wallet.withdraw(amount)
        self._save_portfolio(portfolio)
        return {
            "currency": currency,
            "amount": amount,
            "before": before,
            "after": wallet.balance,
            "rate": rate,
            "value": value,
        }
