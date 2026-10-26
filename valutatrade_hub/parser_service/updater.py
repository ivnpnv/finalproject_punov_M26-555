"""Последовательное обновление источников с сохранением частичного результата."""

from datetime import datetime, timezone
from typing import Any

from valutatrade_hub.constants import PARSER_LOGGER_NAME
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage, normalize_record


class RatesUpdater:
    """Координирует клиентов, проверку измерений, хранилище и журнал операций."""

    def __init__(self, clients: list[BaseApiClient], storage: RatesStorage) -> None:
        self.clients = clients
        self.storage = storage
        self.logger = setup_logging(PARSER_LOGGER_NAME, "parser_log_file")

    def run_update(self) -> dict[str, Any]:
        """Продолжает работу после сбоя клиента; не трогает файлы при полном отказе."""
        self.logger.info("UPDATE_RATES start clients=%d", len(self.clients))
        records = []
        errors = {}
        for client in self.clients:
            try:
                self.logger.info("Получение курсов: %s", client.source)
                rates = client.fetch_rates()
                if not rates or rates.keys() != client.observations.keys():
                    raise ApiRequestError("нет котировок или их метаданных")
                batch = []
                for pair, rate in rates.items():
                    record = normalize_record(client.observations[pair])
                    expected_pair = f"{record['from_currency']}_{record['to_currency']}"
                    if pair != expected_pair or rate != record["rate"]:
                        raise ApiRequestError("курсы и метаданные не совпадают")
                    batch.append(record)
                records.extend(batch)
                self.logger.info(
                    "UPDATE_RATES source=%s result=OK pairs=%d",
                    client.source,
                    len(batch),
                )
            except (ApiRequestError, ValueError) as error:
                errors[client.source] = str(error)
                self.logger.warning(
                    "UPDATE_RATES source=%s result=ERROR error=%s", client.source, error
                )
        if not records:
            self.logger.error("UPDATE_RATES complete result=ERROR")
            raise ApiRequestError("ни один источник не вернул корректные курсы")
        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            self.logger.info(
                "Запись котировок: %s", self.storage.config.rates_file_path
            )
            snapshot = self.storage.save(records, stamp)
        except (OSError, ValueError) as error:
            self.logger.error(
                "UPDATE_RATES storage result=ERROR type=%s", type(error).__name__
            )
            raise
        self.logger.info(
            "UPDATE_RATES complete result=%s received=%d",
            "PARTIAL" if errors else "OK",
            len(records),
        )
        return {
            "snapshot": snapshot,
            "received": len(records),
            "errors": errors,
            "updated": self.storage.updated_count,
        }


API_CLIENTS = {
    "coingecko": CoinGeckoClient,
    "exchangerate": ExchangeRateApiClient,
}


def create_updater(
    config: ParserConfig | None = None, source: str | None = None
) -> RatesUpdater:
    """Собирает выбранные источники; неизвестный источник отклоняет до запросов."""
    config = config if config is not None else ParserConfig()
    if source is not None and source not in API_CLIENTS:
        raise ValueError(f"Неизвестный источник курсов: {source}")
    factories = API_CLIENTS.values() if source is None else [API_CLIENTS[source]]
    return RatesUpdater(
        [factory(config) for factory in factories], RatesStorage(config)
    )
