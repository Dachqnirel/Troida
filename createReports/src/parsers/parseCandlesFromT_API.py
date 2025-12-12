from src.stockConfig import StockConfig
from packages.API.T_InvestAPI import tAPI
from .parseConfigFile import parseConfigFile
import asyncio

async def getCandlesShore(stockConfig: StockConfig) -> tuple[StockConfig, tAPI.pd.DataFrame]:
    """
    Загрузка свечей одной акции, перечисленных в конфигурационном файле arguments.file из Т-инвестиций

    Return:
        turple(StockConfig, DataFrame): Параметры акции и свечи
    """
    candlesDataFrame: tAPI.pd.DataFrame = await tAPI.download_candles(stockConfig.ticker, stockConfig.interval, stockConfig.from_date, stockConfig.to_date)
    return (stockConfig, candlesDataFrame)

async def getCandlesShores(configFile: str):
    """
    Парсинг свечей из T-инвестиции.

    Args:
        configFile (str): Конфигурационный файл .yaml для указания какие акции нужно парсить из Т-инвестиций

    Returns:
        list[tuple[StockConfig, DataFrame]]: Список тьюполов, состоящих из названия акции и датафрейма.
    """    
    stocksConfigs: list[StockConfig] = parseConfigFile(configFile) # парсинг из конфигурационного файла списка акций
    tasks: list = []
    for stockConfig in stocksConfigs:
        coroutineParseCandles = getCandlesShore(stockConfig)
        tasks.append(asyncio.create_task(coroutineParseCandles))
    shoresCandles: list[tuple[StockConfig, tAPI.pd.DataFrame]] = await asyncio.gather(*tasks)
    return shoresCandles