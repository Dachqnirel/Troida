import yaml
from src.stockConfig import StockConfig
from packages.API.T_InvestAPI import tAPI
from datetime import timezone

def parseConfigFile(configPath: str = "./configureScript.yml") -> list[StockConfig]:
    """
    Парсинг конфигурационного файла со сведениями из акций. Передаётся файл при помощи параметра -f при вызове скрипта buildReports.py
    или по умолчанию "./configureScript.yml

    Args:
        configPath (str, optional): Путь к конфигурационному файлу, откуда считываются акции и их характеристики для парсинга. Defaults to "./configureScript.yml".

    Returns:
        list[StockConfig]: список StockConfig со сведениями об акциях
    """    
    with open(file=configPath, encoding='utf-8', mode='r') as file:
        stocksConfig: dict = yaml.safe_load(file)['stock']
        
    stocksConfigs: list[StockConfig] = []
    for _, stockValue in stocksConfig.items():
        dataObject: StockConfig = StockConfig(
            ticker=stockValue['ticker'],
            interval=stockValue['interval'],
            from_date=tAPI.datetime.strptime(stockValue['from_date'], '%d.%m.%Y %H:%M:%S').replace(tzinfo=timezone.utc),
            to_date=tAPI.datetime.strptime(stockValue['to_date'], '%d.%m.%Y %H:%M:%S').replace(tzinfo=timezone.utc)
        )
        stocksConfigs.append(dataObject)
    return stocksConfigs