import yaml
from src.dividendConfig import DividendConfig
from packages.API.T_InvestAPI import tAPI
from datetime import timezone

def parseDividendsConfigFile(configPath: str = "./configureDividends.yml") -> list[DividendConfig]:
    """
    Парсинг конфигурационного файла со сведениями об инструментах для отчёта по дивидендам.
    """
    with open(file=configPath, encoding='utf-8', mode='r') as file:
        stocksConfig: dict = yaml.safe_load(file)['stock']

    configs: list[DividendConfig] = []
    for _, stockValue in stocksConfig.items():
        dataObject: DividendConfig = DividendConfig(
            ticker=stockValue['ticker'],
            from_date=tAPI.datetime.strptime(
                stockValue['from_date'], '%d.%m.%Y %H:%M:%S'
            ).replace(tzinfo=timezone.utc),
            to_date=tAPI.datetime.strptime(
                stockValue['to_date'], '%d.%m.%Y %H:%M:%S'
            ).replace(tzinfo=timezone.utc),
        )
        configs.append(dataObject)

    return configs
