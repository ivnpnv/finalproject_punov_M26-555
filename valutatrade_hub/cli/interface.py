import argparse
import logging
import shlex
import sys
from typing import Any

from prettytable import PrettyTable

from valutatrade_hub.constants import (
    AMOUNT_FORMAT,
    LOGIN_REQUIRED_MESSAGE,
    MONEY_FORMAT,
    PARSER_LOGGER_NAME,
    PRICE_FORMAT,
    RATE_FORMAT,
    TRADE_BASE_CURRENCY,
)
from valutatrade_hub.core.currencies import CURRENCIES, get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    RatesUnavailableError,
)
from valutatrade_hub.core.usecases import WalletService


class WalletCLI:
    """Командный интерфейс управления пользователями, портфелями и курсами."""

    def __init__(self, service: WalletService) -> None:
        self.service = service
        self.current_user = None
        self.parser = self.create_parser()

    def create_parser(self) -> argparse.ArgumentParser:
        """Описывает команды, аргументы и справку argparse."""
        parser = argparse.ArgumentParser(prog="valutatrade")
        commands = parser.add_subparsers(dest="command", required=True)

        for name in ("register", "login"):
            command = commands.add_parser(name)
            command.add_argument("--username", required=True)
            command.add_argument("--password", required=True)

        currency_errors = (
            "Ошибки: неизвестная валюта — проверьте поддерживаемые коды; "
            "сбой получения курса — повторите позже или проверьте сеть."
        )
        portfolio = commands.add_parser("show-portfolio", epilog=currency_errors)
        portfolio.add_argument(
            "--base", default=self.service.settings.get("base_currency")
        )

        for name in ("buy", "sell"):
            errors = currency_errors + " Сумма должна быть положительным числом."
            if name == "sell":
                errors += " Недостаточно средств — уменьшите сумму продажи."
            command = commands.add_parser(name, epilog=errors)
            command.add_argument(
                "--currency", required=True, help="код валюты, например BTC"
            )
            command.add_argument(
                "--amount",
                type=float,
                required=True,
                help="количество валюты; должно быть больше нуля",
            )

        rate = commands.add_parser("get-rate", epilog=currency_errors)
        rate.add_argument("--from", dest="from_currency", required=True)
        rate.add_argument("--to", dest="to_currency", required=True)
        update = commands.add_parser("update-rates", help="обновить курсы через API")
        update.add_argument("--source", choices=("coingecko", "exchangerate"))
        show = commands.add_parser(
            "show-rates", help="показать курсы из локального кэша"
        )
        show.add_argument("--currency", help="показать только указанную валюту")
        show.add_argument("--top", type=int, help="N самых дорогих криптовалют")
        show.add_argument("--base", default=TRADE_BASE_CURRENCY, help="базовая валюта")
        commands.add_parser("help")
        commands.add_parser("exit")
        return parser

    def run(self) -> None:
        """Читает команды, показывает ошибки и продолжает сессию."""
        print("ValutaTrade Hub. Введите help для справки, exit для выхода.")
        while True:
            try:
                line = input("> ")
                if not line.strip():
                    continue
                if not self.execute(line):
                    break
            except SystemExit:
                continue
            except InsufficientFundsError as error:
                print(error)
            except CurrencyNotFoundError as error:
                print(error)
                print("Поддерживаемые валюты: " + ", ".join(CURRENCIES))
                print("Справка по запросу курса: get-rate --help")
            except RatesUnavailableError as error:
                print(error)
            except ApiRequestError as error:
                print(error)
                print("Повторите попытку позже или проверьте подключение к сети.")
            except (ValueError, OSError) as error:
                print(f"Ошибка: {error}")
            except (EOFError, KeyboardInterrupt):
                print()
                break

    def execute(self, line: str) -> bool:
        """Разбирает команду и передаёт её отдельному обработчику."""
        args = self.parser.parse_args(shlex.split(line))
        if args.command == "exit":
            return False
        if args.command == "help":
            self.parser.print_help()
            return True
        if args.command in ("show-portfolio", "buy", "sell"):
            if self.current_user is None:
                print(LOGIN_REQUIRED_MESSAGE)
                return True
        handlers = {
            "register": self._handle_register,
            "login": self._handle_login,
            "show-portfolio": self._handle_portfolio,
            "buy": self._handle_trade,
            "sell": self._handle_trade,
            "get-rate": self._handle_rate,
            "update-rates": self._handle_update_rates,
            "show-rates": self._handle_show_rates,
        }
        handlers[args.command](args)
        return True

    def _handle_update_rates(self, args: argparse.Namespace) -> None:
        """Показывает ход обновления, количество изменений и частичные ошибки."""
        logger = logging.getLogger(PARSER_LOGGER_NAME)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        log_path = self.service.settings.get("parser_log_file")
        try:
            result = self.service.update_rates(source=args.source)
        except ApiRequestError as error:
            print(f"Обновление не выполнено: {error}")
            print(f"Подробности: {log_path}. Повторите попытку позже.")
            return
        finally:
            logger.removeHandler(handler)
            handler.close()
        status = "с ошибками" if result["errors"] else "успешно"
        print(
            f"Обновление завершено {status}. Обновлено курсов: {result['updated']}. "
            f"Получено: {result['received']}."
        )
        print(f"Последнее обновление: {result['snapshot']['last_refresh']}")
        if result["errors"]:
            print(f"Подробности ошибок: {log_path}")

    def _handle_show_rates(self, args: argparse.Namespace) -> None:
        """Выводит таблицу котировок с временем обновления и состоянием TTL."""
        report = self.service.show_rates(args.currency, args.top, args.base)
        print(f"Курсы из кэша (обновление: {report['last_refresh'] or 'не указано'}):")
        table = PrettyTable(["Пара", "Курс", "Время котировки (UTC)", "Статус"])
        table.align = "l"
        for row in report["rows"]:
            table.add_row(
                [
                    row["pair"],
                    format(row["rate"], RATE_FORMAT),
                    row["updated_at"],
                    "актуален" if row["fresh"] else "устарел",
                ]
            )
        if report["rows"]:
            print(table)
        else:
            print("Нет курсов, соответствующих фильтрам.")
        for warning in report["warnings"]:
            print(warning)
        if any(not row["fresh"] for row in report["rows"]):
            print("Есть устаревшие котировки. Выполните update-rates.")

    def _handle_register(self, args: argparse.Namespace) -> None:
        """Регистрирует пользователя и предлагает войти без вывода пароля."""
        user = self.service.register(args.username, args.password)
        print(
            f"Пользователь '{user.username}' зарегистрирован "
            f"(id={user.user_id}). "
            f"Войдите: login --username {user.username} --password <пароль>"
        )

    def _handle_login(self, args: argparse.Namespace) -> None:
        """Сохраняет пользователя текущей сессии после успешного входа."""
        self.current_user = self.service.login(args.username, args.password)
        print(f"Вы вошли как '{self.current_user.username}'")

    def _handle_portfolio(self, args: argparse.Namespace) -> None:
        """Выводит подготовленный сервисом отчёт о портфеле."""
        report = self.service.show_portfolio(self.current_user, args.base)
        self.print_portfolio(report)

    def _handle_trade(self, args: argparse.Namespace) -> None:
        """Вызывает покупку или продажу и выводит подтверждение сделки."""
        operations = {
            "buy": (
                self.service.buy,
                "Покупка выполнена",
                "Оценочная стоимость покупки",
            ),
            "sell": (self.service.sell, "Продажа выполнена", "Оценочная выручка"),
        }
        operation, label, value_label = operations[args.command]
        result = operation(self.current_user, args.currency, args.amount)
        self.print_trade(result, label, value_label)

    def _handle_rate(self, args: argparse.Namespace) -> None:
        """Показывает курс, обратный курс и время обновления."""
        result = self.service.get_rate(args.from_currency, args.to_currency)
        rate = result["rate"]
        updated_at = result["updated_at"].replace("T", " ")
        print(
            f"Курс {args.from_currency}→{args.to_currency}: "
            f"{format(rate, RATE_FORMAT)} (обновлено: {updated_at})"
        )
        print(
            f"Обратный курс {args.to_currency}→{args.from_currency}: "
            f"{format(1 / rate, RATE_FORMAT)}"
        )

    def print_portfolio(self, report: dict[str, Any]) -> None:
        """Выводит балансы и общую оценку в выбранной базовой валюте."""
        base = report["base_currency"]
        print(f"Портфель пользователя '{report['username']}' (база: {base}):")
        if not report["rows"]:
            print("В портфеле пока нет кошельков.")
        for row in report["rows"]:
            balance = format(row["balance"], AMOUNT_FORMAT)
            value = format(row["value"], MONEY_FORMAT)
            print(f"- {row['currency']}: {balance} → {value} {base}")
        print(f"ИТОГО: {format(report['total'], MONEY_FORMAT)} {base}")

    def print_trade(self, result: dict[str, Any], label: str, value_label: str) -> None:
        """Выводит курс сделки, изменение баланса и оценочную стоимость."""
        currency = result["currency"]
        amount = format(result["amount"], AMOUNT_FORMAT)
        price = format(result["rate"], PRICE_FORMAT)
        before = format(result["before"], AMOUNT_FORMAT)
        after = format(result["after"], AMOUNT_FORMAT)
        value = format(result["value"], MONEY_FORMAT)
        print(
            f"{label}: {amount} {currency} "
            f"по курсу {price} {TRADE_BASE_CURRENCY}/{currency}"
        )
        print(get_currency(currency).get_display_info())
        print("Изменения в портфеле:")
        print(f"- {currency}: было {before} → стало {after}")
        print(f"{value_label}: {value} {TRADE_BASE_CURRENCY}")


def main() -> None:
    """Запускает интерактивный интерфейс приложения."""
    WalletCLI(WalletService()).run()
