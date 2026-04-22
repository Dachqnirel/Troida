import argparse


def getOptionsFromCLI() -> argparse.Namespace:
    argParse = argparse.ArgumentParser(
        prog="run futures backtest",
        description=(
            "Запуск фьючерсной стратегии на backtrader "
            "по данным из CSV/Parquet."
        ),
        add_help=True,
    )

    argParse.add_argument(
        "-f",
        "--file",
        action="store",
        required=True,
        help="Путь к YAML-конфигурации бэктеста.",
    )
    argParse.add_argument(
        "-o",
        "--output",
        action="store",
        help="Путь для сохранения JSON-сводки по результатам.",
    )
    argParse.add_argument(
        "--plot",
        action="store_true",
        help="Построить график после завершения бэктеста.",
    )
    argParse.add_argument(
        "--quiet",
        action="store_true",
        help="Не печатать события исполнения ордеров во время прогона.",
    )

    return argParse.parse_args()
