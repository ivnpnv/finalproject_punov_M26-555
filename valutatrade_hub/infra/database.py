"""Общий доступ к JSON с атомарной записью и межпроцессными блокировками."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any, Self

from filelock import FileLock

from valutatrade_hub.constants import JSON_INDENT


class DatabaseManager:
    """Менеджер JSON-файлов с атомарной записью и блокировками."""

    _instance: Self | None = None
    _creation_lock = Lock()

    def __new__(cls) -> Self:
        """Создаёт один экземпляр, включая одновременные вызовы из потоков."""
        with cls._creation_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def read(self, filepath: str | Path, default: Any) -> Any:
        """Читает снимок или возвращает независимое значение по умолчанию."""
        try:
            with Path(filepath).open(encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError:
            return deepcopy(default)
        except json.JSONDecodeError:
            raise ValueError(f"Не удалось прочитать JSON-файл: {filepath}.") from None

    def write(self, filepath: str | Path, data: Any) -> None:
        """Атомарно заменяет файл после сериализации и fsync."""
        path = Path(filepath)
        with self.lock(path):
            temporary_path = None
            try:
                with NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    suffix=".tmp",
                    delete=False,
                ) as file:
                    temporary_path = Path(file.name)
                    json.dump(
                        data,
                        file,
                        ensure_ascii=False,
                        indent=JSON_INDENT,
                        allow_nan=False,
                    )
                    file.flush()
                    os.fsync(file.fileno())
                temporary_path.replace(path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

    @contextmanager
    def lock(self, filepath: str | Path) -> Iterator[None]:
        """Сериализует изменения файла между потоками и процессами."""
        path = Path(filepath).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path) + ".lock", timeout=30, is_singleton=True):
            yield

    @contextmanager
    def edit(self, filepath: str | Path, default: Any) -> Iterator[Any]:
        """Блокирует файл на время чтения, изменения и записи данных."""
        with self.lock(filepath):
            data = self.read(filepath, default)
            original = deepcopy(data)
            yield data
            if data != original:
                self.write(filepath, data)
