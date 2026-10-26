"""История измерений и актуальный снимок курсов."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from valutatrade_hub.core.currencies import validate_code
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.api_clients import positive_rate
from valutatrade_hub.parser_service.config import ParserConfig


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Проверяет измерение и строит воспроизводимый ID из пары и UTC-времени."""
    try:
        source_code = validate_code(record["from_currency"])
        target_code = validate_code(record["to_currency"])
        timestamp = datetime.fromisoformat(record["timestamp"])
        if timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc):
            raise ValueError("Некорректная дата измерения.")
        stamp = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        source = record["source"]
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Не указан источник курса.")
        meta = record.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError("Метаданные должны быть словарём.")
        return {
            "id": f"{source_code}_{target_code}_{stamp}",
            "from_currency": source_code,
            "to_currency": target_code,
            "rate": positive_rate(record["rate"]),
            "timestamp": stamp,
            "source": source,
            "meta": deepcopy(meta),
        }
    except (KeyError, TypeError) as error:
        raise ValueError("Неверная структура измерения курса.") from error


class RatesStorage:
    """Сохраняет историю без дублей и последний срез каждой пары."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config if config is not None else ParserConfig()
        self.database = DatabaseManager()
        self.updated_count = 0

    def save(self, records: list[dict[str, Any]], last_refresh: str) -> dict[str, Any]:
        """Пишет историю перед кэшем; повторный запуск восстановит кэш после сбоя."""
        incoming = [normalize_record(record) for record in records]
        config = self.config
        with self.database.lock(config.history_file_path):
            history = self.database.read(config.history_file_path, [])
            if not isinstance(history, list):
                raise ValueError("История курсов должна содержать JSON-массив.")
            indexed = {item["id"]: item for item in map(normalize_record, history)}
            for record in incoming:
                indexed.setdefault(record["id"], record)
            history = list(indexed.values())
            pairs = {}
            for record in history:
                pair = f"{record['from_currency']}_{record['to_currency']}"
                previous = pairs.get(pair)
                if previous is None or datetime.fromisoformat(record["timestamp"]) > (
                    datetime.fromisoformat(previous["updated_at"])
                ):
                    pairs[pair] = {
                        "rate": record["rate"],
                        "updated_at": record["timestamp"],
                        "source": record["source"],
                    }
            previous_snapshot = self.database.read(config.rates_file_path, {})
            previous_pairs = (
                previous_snapshot.get("pairs", {})
                if isinstance(previous_snapshot, dict)
                else {}
            )
            if not isinstance(previous_pairs, dict):
                previous_pairs = {}
            updated_count = sum(
                previous_pairs.get(pair) != value for pair, value in pairs.items()
            )
            snapshot = {"pairs": pairs, "last_refresh": last_refresh}
            self.database.write(config.history_file_path, history)
            self.database.write(config.rates_file_path, snapshot)
            self.updated_count = updated_count
        return snapshot
