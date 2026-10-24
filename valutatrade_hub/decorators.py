import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from valutatrade_hub.constants import (
    ACTION_LOGGER_NAME,
    AMOUNT_FORMAT,
    PRICE_FORMAT,
    TRADE_BASE_CURRENCY,
)
from valutatrade_hub.core.models import User


def log_action(verbose: bool = False) -> Callable:
    """Записывает результат сделки и ошибку, сохраняя проброс исключений."""

    def decorator(func: Callable) -> Callable:
        """Оборачивает метод покупки или продажи с сохранением его метаданных."""

        @wraps(func)
        def wrapper(
            self: Any, user: User | None, currency: str, amount: float
        ) -> dict[str, Any]:
            """Выполняет сделку и добавляет контекст в журнал действий."""
            logger = logging.getLogger(ACTION_LOGGER_NAME)
            username = user.username if user is not None else None
            amount_text = (
                format(amount, AMOUNT_FORMAT)
                if type(amount) in (int, float)
                else repr(amount)
            )
            context = (
                f"{func.__name__.upper()} user={username!r} "
                f"currency={currency!r} amount={amount_text}"
            )
            try:
                result = func(self, user, currency, amount)
            except Exception as error:
                logger.info(
                    "%s base=%r result=ERROR error_type=%s error_message=%r",
                    context,
                    TRADE_BASE_CURRENCY,
                    type(error).__name__,
                    str(error),
                )
                raise

            details = ""
            if verbose:
                details = (
                    f" balance_before={format(result['before'], AMOUNT_FORMAT)}"
                    f" balance_after={format(result['after'], AMOUNT_FORMAT)}"
                )
            logger.info(
                "%s rate=%s base=%r result=OK%s",
                context,
                format(result["rate"], PRICE_FORMAT),
                TRADE_BASE_CURRENCY,
                details,
            )
            return result

        return wrapper

    return decorator
