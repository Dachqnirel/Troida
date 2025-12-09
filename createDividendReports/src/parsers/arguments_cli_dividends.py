import argparse

def getOptionsFromCLI() -> argparse.Namespace:
    """
    Получить параметры из CLI при запуске скрипта отчётов по дивидендам.
    """
    argParse: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="create dividends reports from T-Invest",
        description="""
        Создание отчётов по дивидендам из T-инвестиций по инструментам,
        перечисленным в .yaml конфигурационном файле
        """,
        add_help=True
    )

    argParse.add_argument(
        '-f', '--file',
        action='store',
        help="Файл конфигурации yaml с параметрами инструментов для отчётов по дивидендам",
        required=True
    )
    argParse.add_argument(
        '-d', '--destination',
        action='store',
        default='./dividends_reports',
        help="Директория для сохранения отчётов по дивидендам.",
        required=True
    )

    inputData: argparse.Namespace = argParse.parse_args()
    return inputData
