import argparse
import shlex
from typing import Any

from valutatrade_hub.core.currencies import CURRENCIES, get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.usecases import WalletService


class WalletCLI:
    def __init__(self, service):
        self.service = service
        self.current_user = None
        self.parser = self.create_parser()

    def create_parser(self):
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
        commands.add_parser("help")
        commands.add_parser("exit")
        return parser

    def run(self):
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
            except ApiRequestError as error:
                print(error)
                print("Повторите попытку позже или проверьте подключение к сети.")
            except (ValueError, OSError) as error:
                print(f"Ошибка: {error}")
            except (EOFError, KeyboardInterrupt):
                print()
                break

    def execute(self, line):
        args = self.parser.parse_args(shlex.split(line))

        if args.command == "exit":
            return False
        if args.command == "help":
            self.parser.print_help()
            return True

        if args.command in ("show-portfolio", "buy", "sell"):
            if self.current_user is None:
                print("Сначала выполните login")
                return True

        if args.command == "register":
            user = self.service.register(args.username, args.password)
            print(
                f"Пользователь '{user.username}' зарегистрирован "
                f"(id={user.user_id}). "
                f"Войдите: login --username {user.username} --password <пароль>"
            )

        elif args.command == "login":
            self.current_user = self.service.login(args.username, args.password)
            print(f"Вы вошли как '{self.current_user.username}'")

        elif args.command == "show-portfolio":
            report = self.service.show_portfolio(self.current_user, args.base)
            self.print_portfolio(report)

        elif args.command in ("buy", "sell"):
            if args.command == "buy":
                result = self.service.buy(self.current_user, args.currency, args.amount)
                label = "Покупка выполнена"
                value_label = "Оценочная стоимость покупки"
            else:
                result = self.service.sell(
                    self.current_user, args.currency, args.amount
                )
                label = "Продажа выполнена"
                value_label = "Оценочная выручка"
            self.print_trade(result, label, value_label)

        elif args.command == "get-rate":
            result = self.service.get_rate(args.from_currency, args.to_currency)
            rate = result["rate"]
            updated_at = result["updated_at"].replace("T", " ")
            print(
                f"Курс {args.from_currency}→{args.to_currency}: {rate:.8f} "
                f"(обновлено: {updated_at})"
            )
            print(
                f"Обратный курс {args.to_currency}→{args.from_currency}: {1 / rate:.8f}"
            )

        return True

    def print_portfolio(self, report):
        base = report["base_currency"]
        print(f"Портфель пользователя '{report['username']}' (база: {base}):")
        if not report["rows"]:
            print("В портфеле пока нет кошельков.")
        for row in report["rows"]:
            print(
                f"- {row['currency']}: {row['balance']:.4f} "
                f"→ {row['value']:,.2f} {base}"
            )
        print(f"ИТОГО: {report['total']:,.2f} {base}")

    def print_trade(self, result: dict[str, Any], label: str, value_label: str) -> None:
        currency = result["currency"]
        print(
            f"{label}: {result['amount']:.4f} {currency} "
            f"по курсу {result['rate']:.2f} USD/{currency}"
        )
        print(get_currency(currency).get_display_info())
        print("Изменения в портфеле:")
        print(
            f"- {currency}: было {result['before']:.4f} → стало {result['after']:.4f}"
        )
        print(f"{value_label}: {result['value']:,.2f} USD")


def main():
    WalletCLI(WalletService()).run()
