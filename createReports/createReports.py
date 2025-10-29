# инициализация скрипта
import sys
import os
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

# основной код скрипта
from packages.core import logging
from src.parsers.arguments_cli import getOptionsFromCLI, argparse
from src.parsers.parseCandlesFromT_API import getCandlesShores
from src import buildReports
import asyncio



    
async def main():
    candles_dataframes = await getCandlesShores(arguments.file)
    for stockConfig, dataframe in candles_dataframes:
        buildReports.one_shore_build_report(stockConfig, dataframe, arguments.destination, buildReports.ReportType.UNVERIFIED_REPORT)


if __name__ == '__main__':
    arguments: argparse.Namespace = getOptionsFromCLI() # аргументы из CLI
    asyncio.run(main())