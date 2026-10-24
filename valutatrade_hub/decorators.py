import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from valutatrade_hub.core.models import User


def log_action(verbose: bool = False) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(
            self: Any, user: User | None, currency: str, amount: float
        ) -> dict[str, Any]:
            logger = logging.getLogger("valutatrade.actions")
            username = user.username if user is not None else None
            amount_text = (
                f"{amount:.4f}" if type(amount) in (int, float) else repr(amount)
            )
            context = (
                f"{func.__name__.upper()} user={username!r} "
                f"currency={currency!r} amount={amount_text}"
            )
            try:
                result = func(self, user, currency, amount)
            except Exception as error:
                logger.info(
                    "%s base='USD' result=ERROR error_type=%s error_message=%r",
                    context,
                    type(error).__name__,
                    str(error),
                )
                raise

            details = ""
            if verbose:
                details = (
                    f" balance_before={result['before']:.4f}"
                    f" balance_after={result['after']:.4f}"
                )
            logger.info(
                "%s rate=%.2f base='USD' result=OK%s",
                context,
                result["rate"],
                details,
            )
            return result

        return wrapper

    return decorator
