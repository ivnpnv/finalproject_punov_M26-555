import tomllib
from pathlib import Path
from typing import Any, Self

from valutatrade_hub.constants import DEFAULT_SETTINGS


class SettingsLoader:
    """Один экземпляр конфигурации на процесс, с явной перезагрузкой."""

    _instance = None

    def __new__(cls) -> Self:
        """Создаёт экземпляр при первом обращении и повторно возвращает его."""
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
        settings = DEFAULT_SETTINGS.copy()
        if self._filepath.exists():
            with self._filepath.open("rb") as file:
                config = tomllib.load(file)
            settings.update(config.get("tool", {}).get("valutatrade", {}))
        self._settings = settings
