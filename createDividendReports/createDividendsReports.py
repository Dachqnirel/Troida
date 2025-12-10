# инициализация скрипта
import sys
import os
from pathlib import Path
import asyncio

sys.path.append(str(Path(__file__).parent.parent))

from src.parsers.arguments_cli_dividends import getOptionsFromCLI, argparse

async def main():
    arguments: argparse.Namespace = getOptionsFromCLI()
    from packages.core import logging
    logging.setup_logging(['./createDividendReports/logging_config.yaml', './logging_config.yaml'])

    from src import buildDividendsReports
    from src.parsers.parseDividendsFromT_API import getDividendsForInstruments
    # Получаем дивиденды из API
    instruments_dividends = await getDividendsForInstruments(arguments.file)
    # divConfig: DividendConfig
    # dataframe: pd.Dataframe
    for divConfig, dataframe in instruments_dividends:
        if dataframe is not None:
            logging.logger.info(f"Обработка инструмента {divConfig.ticker} с {len(dataframe)} строками дивидендов")

            # Сохраняем базовый отчёт
            buildDividendsReports.one_instrument_build_dividends_report(
                divConfig,
                dataframe,
                arguments.destination,
                buildDividendsReports.DividendReportType.RAW_REPORT
            )
            logging.logger.info(
                f"Сохранён отчёт по дивидендам для {divConfig.ticker} с {len(dataframe)} строками"
            )

    logging.logger.info("В СЛУЧАЕ ЕСЛИ В ОТЧЁТАХ НЕ ЗАГРУЖЕН КАКАЯ-ТО ОПРЕДЕЛЕННАЯ КОМПАНИЯ, ЗНАЧИТ Т-АПИ НЕ ПРЕДОСТАВЛЯЕТ ИНФОРМАЦИЮ ПО АПИ")
if __name__ == '__main__':
    asyncio.run(main())
