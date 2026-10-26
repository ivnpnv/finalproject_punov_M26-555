"""Запуск Parser Service вручную или циклически в отдельном процессе."""

import argparse
import time

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import RatesUpdater, create_updater


def run_scheduler(updater: RatesUpdater, interval: float) -> None:
    """Повторяет обновление через заданную паузу; Ctrl+C завершает процесс."""
    while True:
        try:
            updater.run_update()
        except (ApiRequestError, OSError, ValueError) as error:
            updater.logger.error(
                "SCHEDULER update failed type=%s", type(error).__name__
            )
        time.sleep(interval)


def main() -> None:
    """Обрабатывает одноразовый запуск и запуск по интервалу в секундах."""
    parser = argparse.ArgumentParser(prog="valutatrade-parser")
    parser.add_argument("--once", action="store_true", help="обновить и завершить")
    parser.add_argument("--interval", type=float, help="пауза между обновлениями")
    args = parser.parse_args()
    try:
        config = (
            ParserConfig()
            if args.interval is None
            else ParserConfig(update_interval=args.interval)
        )
        updater = create_updater(config)
        if args.once:
            result = updater.run_update()
            print(f"Получено котировок: {result['received']}")
            for source, error in result["errors"].items():
                print(f"{source}: {error}")
        else:
            run_scheduler(updater, config.update_interval)
    except KeyboardInterrupt:
        print("Обновление остановлено.")
    except (ApiRequestError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
