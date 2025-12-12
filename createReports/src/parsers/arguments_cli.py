import argparse
def getOptionsFromCLI() -> argparse.Namespace:
    """
    Получить параметры из CLI при запуске скрипта

    Returns:
        argparse.Namespace: объект датакласс с параметрами.
    """    
    argParse: argparse.ArgumentParser = argparse.ArgumentParser(prog="create reports from shores T-Invest",
                        description="""
                        Создание отчётов из T-инвестиций по акциями, перечисленным в .yaml конфигурационном файле""",
                        add_help=True)

    argParse.add_argument('-f', '--file', action='store', help="Файл конфигурации yaml, из которого вытаскиваются параметры акций, по которым необходимо создать отчёт", required=True)
    argParse.add_argument('-d', '--destination', action='store', default='./reports', help="Директория для сохранения отчётов.", required=True)
    argParse.add_argument('-m', '--anomaly-mode', choices=["remove", "fix"], default="remove", help="Режим обработки аномалий: 'remove' — удалять, 'fix' — исправлять .", required=True)
    inputData: argparse.Namespace = argParse.parse_args() # парсинг аргументов из командной строки
    return inputData
