import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from valutatrade_hub.constants import ACTION_LOGGER_NAME, LOG_DATE_FORMAT
from valutatrade_hub.infra.settings import SettingsLoader


def setup_logging(
    logger_name: str = ACTION_LOGGER_NAME, file_setting: str = "log_file"
) -> logging.Logger:
    """Настраивает один файловый обработчик с ротацией без дублирования записей."""
    settings = SettingsLoader()
    filepath = Path(settings.get(file_setting)).resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(logger_name)
    logger.setLevel(settings.get("log_level"))
    logger.propagate = False

    handler = next(
        (item for item in logger.handlers if isinstance(item, RotatingFileHandler)),
        None,
    )
    if handler is not None and handler.baseFilename != str(filepath):
        logger.removeHandler(handler)
        handler.close()
        handler = None

    if handler is None:
        handler = RotatingFileHandler(filepath, encoding="utf-8")
        logger.addHandler(handler)

    handler.maxBytes = settings.get("log_max_bytes")
    handler.backupCount = settings.get("log_backup_count")
    handler.setFormatter(
        logging.Formatter(settings.get("log_format"), datefmt=LOG_DATE_FORMAT)
    )
    return logger
