import hashlib
import math

from valutatrade_hub.core.utils import RateService


class User:
    def __init__(self, user_id, username, hashed_password, salt, registration_date):
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @property
    def user_id(self):
        return self._user_id

    @property
    def username(self):
        return self._username

    @username.setter
    def username(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        self._username = value.strip()

    @property
    def hashed_password(self):
        return self._hashed_password

    @property
    def salt(self):
        return self._salt

    @property
    def registration_date(self):
        return self._registration_date

    def get_user_info(self):
        print(f"ID: {self._user_id}")
        print(f"Имя пользователя: {self._username}")
        print(f"Дата регистрации: {self._registration_date}")

    def change_password(self, new_password):
        if not isinstance(new_password, str) or len(new_password) < 4:
            raise ValueError("Пароль должен содержать не менее 4 символов.")
        password_with_salt = (new_password + self._salt).encode("utf-8")
        self._hashed_password = hashlib.sha256(password_with_salt).hexdigest()

    def verify_password(self, password):
        password_with_salt = (password + self._salt).encode("utf-8")
        password_hash = hashlib.sha256(password_with_salt).hexdigest()
        return password_hash == self._hashed_password


class Wallet:
    def __init__(self, currency_code, balance=0.0):
        self.currency_code = currency_code
        self.balance = balance

    @property
    def balance(self):
        return self._balance

    @balance.setter
    def balance(self, value):
        if type(value) not in (int, float):
            raise ValueError("Баланс должен быть числом.")
        if not math.isfinite(value) or value < 0:
            raise ValueError("Баланс должен быть конечным неотрицательным числом.")
        self._balance = float(value)

    def deposit(self, amount):
        if type(amount) not in (int, float):
            raise ValueError("Сумма пополнения должна быть числом.")
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError(
                "Сумма пополнения должна быть конечным положительным числом."
            )

        self.balance = self.balance + amount

    def withdraw(self, amount):
        if type(amount) not in (int, float):
            raise ValueError("Сумма снятия должна быть числом.")
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Сумма снятия должна быть конечным положительным числом.")
        if amount > self.balance:
            raise ValueError("Недостаточно средств на балансе.")

        self.balance = self.balance - amount

    def get_balance_info(self):
        print(f"Баланс: {self.balance} {self.currency_code}")


class Portfolio:
    def __init__(self, user, wallets=None):
        self._user = user
        self._user_id = user.user_id
        self._wallets = wallets.copy() if wallets is not None else {}

    @property
    def user(self):
        return self._user

    @property
    def wallets(self):
        return self._wallets.copy()

    def add_currency(self, currency_code):
        if currency_code in self._wallets:
            raise ValueError(f"Кошелёк {currency_code} уже существует.")

        self._wallets[currency_code] = Wallet(currency_code)

    def get_wallet(self, currency_code):
        if currency_code not in self._wallets:
            raise ValueError(f"Кошелёк {currency_code} не найден.")

        return self._wallets[currency_code]

    def get_total_value(self, base_currency="USD", rate_service=None):
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
