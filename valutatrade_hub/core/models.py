import hashlib
import math
from datetime import datetime

from valutatrade_hub.constants import TRADE_BASE_CURRENCY
from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import RateService, validate_amount, validate_password


class User:
    """Пользователь с неизменяемым ID и хешем пароля с солью."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @property
    def user_id(self) -> int:
        """Возвращает неизменяемый идентификатор пользователя."""
        return self._user_id

    @property
    def username(self) -> str:
        """Возвращает или проверяет непустое имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        """Возвращает или проверяет непустое имя пользователя."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        """Возвращает хеш для сохранения в хранилище."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Возвращает соль для сохранения рядом с хешем."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Возвращает дату регистрации пользователя."""
        return self._registration_date

    def get_user_info(self) -> None:
        """Печатает общие сведения без хеша и соли."""
        print(f"ID: {self._user_id}")
        print(f"Имя пользователя: {self._username}")
        print(f"Дата регистрации: {self._registration_date}")

    def change_password(self, new_password: str) -> None:
        """Проверяет пароль и заменяет его хеш с сохранением соли."""
        validate_password(new_password)
        password_with_salt = (new_password + self._salt).encode("utf-8")
        self._hashed_password = hashlib.sha256(password_with_salt).hexdigest()

    def verify_password(self, password: str) -> bool:
        """Сравнивает хеш введённого пароля с сохранённым."""
        if not isinstance(password, str):
            return False
        password_with_salt = (password + self._salt).encode("utf-8")
        password_hash = hashlib.sha256(password_with_salt).hexdigest()
        return password_hash == self._hashed_password


class Wallet:
    """Баланс одной зарегистрированной валюты с проверками на уровне модели."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        self._currency_code = get_currency(currency_code).code
        self.balance = balance

    @property
    def currency_code(self) -> str:
        """Код кошелька нельзя изменить после создания."""
        return self._currency_code

    @property
    def balance(self) -> float:
        """Возвращает или проверяет конечный неотрицательный баланс."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        """Возвращает или проверяет конечный неотрицательный баланс."""
        if type(value) not in (int, float):
            raise ValueError("Баланс должен быть числом.")
        if not math.isfinite(value) or value < 0:
            raise ValueError("Баланс должен быть конечным неотрицательным числом.")
        self._balance = float(value)

    def deposit(self, amount: float) -> None:
        """Увеличивает баланс на конечную положительную сумму."""
        amount = validate_amount(amount)
        self.balance = self.balance + amount

    def withdraw(self, amount: float) -> None:
        """Снимает сумму; при нехватке средств сохраняет баланс и выбрасывает ошибку."""
        amount = validate_amount(amount)
        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount, self.currency_code)

        self.balance = self.balance - amount

    def get_balance_info(self) -> None:
        """Печатает текущий баланс и код валюты."""
        print(f"Баланс: {self.balance} {self.currency_code}")


class Portfolio:
    """Кошельки одного пользователя и их оценка в выбранной валюте."""

    def __init__(self, user: User, wallets: dict[str, Wallet] | None = None) -> None:
        self._user = user
        self._user_id = user.user_id
        self._wallets = wallets.copy() if wallets is not None else {}

    @property
    def user(self) -> User:
        """Возвращает владельца портфеля без возможности замены."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Возвращает копию словаря; объекты кошельков остаются общими."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> None:
        """Создаёт кошелёк зарегистрированной валюты, отклоняя дубликаты."""
        if currency_code in self._wallets:
            raise ValueError(f"Кошелёк {currency_code} уже существует.")

        self._wallets[currency_code] = Wallet(currency_code)

    def get_wallet(self, currency_code: str) -> Wallet:
        """Возвращает существующий кошелёк или выбрасывает ValueError."""
        if currency_code not in self._wallets:
            raise ValueError(f"Кошелёк {currency_code} не найден.")

        return self._wallets[currency_code]

    def get_total_value(
        self,
        base_currency: str = TRADE_BASE_CURRENCY,
        rate_service: RateService | None = None,
    ) -> float:
        """Суммирует стоимости кошельков через единый сервис курсов."""
        if rate_service is None:
            rate_service = RateService()
        rate_service.get_rate(base_currency, base_currency)

        total = 0.0
        for currency_code, wallet in self._wallets.items():
            rate = rate_service.get_rate(currency_code, base_currency)["rate"]
            total += wallet.balance * rate
        if not math.isfinite(total):
            raise ValueError("Стоимость портфеля выходит за допустимый диапазон.")

        return total
