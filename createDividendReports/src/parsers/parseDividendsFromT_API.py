from src.dividendConfig import DividendConfig
from packages.API.T_InvestAPI import tAPI
from .parseDividendsConfigFile import parseDividendsConfigFile
import asyncio

async def getDividendsForInstrument(divConfig: DividendConfig) -> tuple[DividendConfig, tAPI.pd.DataFrame]:
    """
    Загрузка дивидендов по одному инструменту из T-инвестиций.
    """
    dividends_df: tAPI.pd.DataFrame = await tAPI.download_dividends(
        divConfig.ticker,
        divConfig.from_date,
        divConfig.to_date,
    )
    return (divConfig, dividends_df)

async def getDividendsForInstruments(configFile: str):
    """
    Парсинг дивидендов по всем инструментам из T-инвестиций.
    """
    configs: list[DividendConfig] = parseDividendsConfigFile(configFile)
    tasks: list = []
    for divConfig in configs:
        coroutineParseDividends = getDividendsForInstrument(divConfig)
        tasks.append(asyncio.create_task(coroutineParseDividends))

    instruments_dividends: list[tuple[DividendConfig, tAPI.pd.DataFrame]] = await asyncio.gather(*tasks)
    return instruments_dividends
