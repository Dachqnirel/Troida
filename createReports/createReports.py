# инициализация скрипта
import sys
import os
from pathlib import Path
import asyncio

sys.path.append(str(Path(__file__).parent.parent))

# основной код скрипта
from src.parsers.arguments_cli import getOptionsFromCLI, argparse


async def main():
    arguments: argparse.Namespace = getOptionsFromCLI()
    
    from packages.core import logging
    logging.setup_logging(['./createReports/logging_config.yaml', './logging_config.yaml'])
    from packages.data.checkAnomalies.find_anomalies import CheckAnomalyCandle
    from src import buildReports
    from src.parsers.parseCandlesFromT_API import getCandlesShores
    
    # Получаем свечи из API
    candles_dataframes = await getCandlesShores(arguments.file)
    logging.logger.info(candles_dataframes[0][1].dtypes)

    for stockConfig, dataframe in candles_dataframes:
        logging.logger.info(f"Обработка акции {stockConfig.ticker} с {len(dataframe)} свечами")

        # Сначала сохраняем непроверенный отчёт
        buildReports.one_shore_build_report(
            stockConfig,
            dataframe,
            arguments.destination,
            buildReports.ReportType.UNVERIFIED_REPORT
        )
        logging.logger.info(f"Сохранён непроверенный отчёт для {stockConfig.ticker}")

        
        # Выбор стратегии обработки аномалий
        verified_dataframe, anomalies_report = CheckAnomalyCandle.checkAnomalyInCandles(
            dataframe,
            mode=arguments.anomaly_mode  # <-- добавляем этот аргумент
        )

        if arguments.anomaly_mode == "remove":
            logging.logger.info("Режим: удаление аномалий")
        elif arguments.anomaly_mode == "fix":
            logging.logger.info("Режим: исправление аномалий")
 
        # Детальный отчёт об аномалиях
        if anomalies_report:
            total_anomalies = sum(
                len(anomalies)
                for anomalies in anomalies_report.values()
                if anomalies is not None and not anomalies.empty
            )
            logging.logger.info(f"Отчёт по аномалиям для {stockConfig.ticker}:")
            logging.logger.info(f"Всего обнаружено аномалий: {total_anomalies}")

            for anomaly_type, anomalies in anomalies_report.items():
                if anomalies is not None and not anomalies.empty:
                    logging.logger.info(f"  - {anomaly_type}: {len(anomalies)}")
                    
        # Сохраняем проверенный отчёт
        buildReports.one_shore_build_report(
            stockConfig,
            verified_dataframe,
            arguments.destination,
            buildReports.ReportType.VERIFIED_REPORT
        )
        logging.logger.info(
            f"Сохранён проверенный отчёт для {stockConfig.ticker} с {len(verified_dataframe)} свечами"
        )



if __name__ == '__main__':
    asyncio.run(main())
