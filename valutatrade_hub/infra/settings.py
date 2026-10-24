import tomllib
from pathlib import Path
from typing import Any, Self


class SettingsLoader:
    _instance = None

    # __new__ проще метакласса: повторный вызов возвращает тот же объект.
    def __new__(cls) -> Self:
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._filepath = Path.cwd() / "pyproject.toml"
            instance.reload()
            cls._instance = instance
        return cls._instance

    def get(self, key: str, default: Any = None) -> Any:
        """Возвращает настройку или default, если ключ не задан."""
        return self._settings.get(key, default)

    def reload(self) -> None:
        """Заново читает настройки из секции tool.valutatrade."""
        settings = {
            "data_dir": "data",
            "users_file": "users.json",
            "portfolios_file": "portfolios.json",
            "rates_file": "rates.json",
            "rates_ttl_seconds": 300,
            "base_currency": "USD",
            "log_file": "logs/actions.log",
            "log_format": "%(levelname)s %(asctime)s %(message)s",
            "log_level": "INFO",
            "log_max_bytes": 1_048_576,
            "log_backup_count": 3,
        }
        if self._filepath.exists():
            with self._filepath.open("rb") as file:
                config = tomllib.load(file)
            settings.update(config.get("tool", {}).get("valutatrade", {}))
        self._settings = settings
