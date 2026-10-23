import argparse
import shlex

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

        portfolio = commands.add_parser("show-portfolio")
        portfolio.add_argument("--base", default="USD")

        for name in ("buy", "sell"):
            command = commands.add_parser(name)
            command.add_argument("--currency", required=True)
            command.add_argument("--amount", type=float, required=True)

        rate = commands.add_parser("get-rate")
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
                result = self.service.buy(
                    self.current_user, args.currency, args.amount
                )
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
                f"Обратный курс {args.to_currency}→{args.from_currency}: "
                f"{1 / rate:.8f}"
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

    def print_trade(self, result, label, value_label):
        currency = result["currency"]
        print(
            f"{label}: {result['amount']:.4f} {currency} "
            f"по курсу {result['rate']:.2f} USD/{currency}"
        )
        print("Изменения в портфеле:")
        print(
            f"- {currency}: было {result['before']:.4f} "
            f"→ стало {result['after']:.4f}"
        )
        print(f"{value_label}: {result['value']:,.2f} USD")


def main():
    WalletCLI(WalletService()).run()
