import hashlib


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
