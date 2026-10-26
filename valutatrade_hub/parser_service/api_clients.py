"""HTTP-клиенты с единым интерфейсом и метаданными измерений."""

import math
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig


def positive_rate(value: Any) -> float:
    """Проверяет конечный положительный курс без приведения строк и bool."""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ApiRequestError("источник вернул некорректный курс")
    return float(value)


def api_timestamp(value: Any) -> str:
    """Преобразует время котировки из ответа API в ISO 8601 UTC."""
    try:
        if type(value) in (int, float):
            date = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            date = parsedate_to_datetime(value)
        else:
            raise ValueError
        if date.tzinfo is None:
            raise ValueError
        return date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError, OSError):
        raise ApiRequestError("некорректное время обновления источника") from None


class BaseApiClient(ABC):
    """Возвращает курсы пар; observations содержит время и источник замеров."""

    source: str

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config if config is not None else ParserConfig()
        self.observations: dict[str, dict[str, Any]] = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Получает проверенные курсы; при сбое выбрасывает ApiRequestError."""

    def _request(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Выполняет GET; не включает URL с ключом в исключения и логи."""
        started = time.monotonic()
        try:
            with requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.request_timeout,
                allow_redirects=False,
            ) as response:
                status = response.status_code
                if status != 200:
                    reasons = {
                        401: "ошибка авторизации: проверьте API-ключ",
                        403: "доступ к API запрещён",
                        429: "лимит запросов исчерпан; повторите позже",
                    }
                    reason = reasons.get(status, "ошибка HTTP")
                    raise ApiRequestError(f"{self.source}: {reason} ({status})")
                payload = response.json()
                meta = {
                    "request_ms": round((time.monotonic() - started) * 1000),
                    "status_code": status,
                }
                if response.headers.get("ETag"):
                    meta["etag"] = response.headers["ETag"]
        except requests.exceptions.RequestException:
            raise ApiRequestError(
                f"{self.source}: ошибка сети или ответа API"
            ) from None
        except ValueError:
            raise ApiRequestError(f"{self.source}: ответ не является JSON") from None
        if not isinstance(payload, dict):
            raise ApiRequestError(f"{self.source}: ожидался JSON-объект")
        return payload, meta

    def _record(
        self, code: str, rate: float, timestamp: str, meta: dict[str, Any]
    ) -> dict[str, Any]:
        """Создаёт унифицированное измерение для истории и кэша."""
        return {
            "from_currency": code,
            "to_currency": self.config.base_currency,
            "rate": rate,
            "timestamp": timestamp,
            "source": self.source,
            "meta": meta,
        }


class CoinGeckoClient(BaseApiClient):
    """Получает выбранные криптовалюты одним пакетным запросом."""

    source = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        """Возвращает цены монет и сохраняет метаданные успешного ответа."""
        self.observations = {}
        config = self.config
        headers = {}
        if config.coingecko_api_key:
            headers["x-cg-demo-api-key"] = config.coingecko_api_key
        payload, meta = self._request(
            config.coingecko_url,
            {
                "ids": ",".join(
                    config.crypto_id_map[c] for c in config.crypto_currencies
                ),
                "vs_currencies": config.base_currency.lower(),
                "include_last_updated_at": "true",
            },
            headers,
        )
        records = {}
        for code in config.crypto_currencies:
            raw_id = config.crypto_id_map[code]
            item = payload.get(raw_id)
            if not isinstance(item, dict):
                raise ApiRequestError(f"{self.source}: отсутствует котировка {code}")
            rate = positive_rate(item.get(config.base_currency.lower()))
            timestamp = api_timestamp(item.get("last_updated_at"))
            records[f"{code}_{config.base_currency}"] = self._record(
                code, rate, timestamp, {**meta, "raw_id": raw_id}
            )
        self.observations = records
        return {pair: record["rate"] for pair, record in records.items()}


class ExchangeRateApiClient(BaseApiClient):
    """Получает фиатные курсы и рассчитывает стоимость валюты в базовой валюте."""

    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict[str, float]:
        """Разбирает conversion_rates официального Standard API."""
        self.observations = {}
        config = self.config
        if not config.exchangerate_api_key:
            raise ApiRequestError("не задана переменная EXCHANGERATE_API_KEY")
        url = (
            f"{config.exchangerate_api_url}/{config.exchangerate_api_key}"
            f"/latest/{config.base_currency}"
        )
        payload, meta = self._request(url)
        if payload.get("result") != "success":
            reasons = {
                "invalid-key": "неверный API-ключ",
                "inactive-account": "аккаунт не активирован",
                "quota-reached": "лимит запросов исчерпан",
            }
            error_type = payload.get("error-type")
            reason = (
                reasons.get(error_type, "некорректный ответ API")
                if isinstance(error_type, str)
                else "некорректный ответ API"
            )
            raise ApiRequestError(f"{self.source}: {reason}")
        rates = payload.get("conversion_rates")
        if payload.get("base_code") != config.base_currency or not isinstance(
            rates, dict
        ):
            raise ApiRequestError(f"{self.source}: неверная база или conversion_rates")
        timestamp = api_timestamp(
            payload.get("time_last_update_unix", payload.get("time_last_update_utc"))
        )
        records = {}
        for code in config.fiat_currencies:
            rate = positive_rate(1 / positive_rate(rates.get(code)))
            records[f"{code}_{config.base_currency}"] = self._record(
                code, rate, timestamp, meta.copy()
            )
        self.observations = records
        return {pair: record["rate"] for pair, record in records.items()}
