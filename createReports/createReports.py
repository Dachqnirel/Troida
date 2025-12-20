# инициализация скрипта
import sys
import os
from pathlib import Path
import asyncio
import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))

# основной код скрипта
from src.parsers.arguments_cli import getOptionsFromCLI, argparse
from packages.data.interpolate import interpolate_missing_intervals

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

        # ========== ПРОВЕРКА ПОЛНОТЫ ДАННЫХ ==========
        # Добавлено: проверка полноты данных и вставка пропущенных интервалов
        from packages.data.completeness.data_completeness import DataCompletenessValidator
        
        print(f"\n{'='*60}")
        print(f"АНАЛИЗ ПОЛНОТЫ ДАННЫХ: {stockConfig.ticker}")
        print(f"{'='*60}")
        
        # Определяем интервал в минутах из конфига
        interval_sec = interval_minutes = interval_hours = interval_days = interval_week = interval_month = 0
        if stockConfig.interval == '5S':
            interval_sec = 5
        elif stockConfig.interval == '10S':
            interval_sec = 10
        elif stockConfig.interval == '30S':
            interval_sec = 30
        elif stockConfig.interval == '1M':
            interval_minutes = 1
        elif stockConfig.interval == '2M':
            interval_minutes = 2
        elif stockConfig.interval == '3M':
            interval_minutes = 3
        elif stockConfig.interval == '5M':
            interval_minutes = 5
        elif stockConfig.interval == '10M':
            interval_minutes = 10
        elif stockConfig.interval == '15M':
            interval_minutes = 15
        if stockConfig.interval == '1H':
            interval_hours = 1
        elif stockConfig.interval == '2H':
            interval_hours = 2
        elif stockConfig.interval == '4H':
            interval_hours = 4
        elif stockConfig.interval == '1D':
            interval_days = 1
        elif stockConfig.interval == '1W':
            interval_week = 1
        elif stockConfig.interval == 'M':
            interval_month = 1
            
        
        # Проверяем полноту данных
        completeness_report = DataCompletenessValidator.validate_data_completeness_by_interval(
            df=dataframe,
            interval_secs=interval_sec,
            interval_minutes=interval_minutes,
            interval_hours=interval_hours,
            interval_days=interval_days,
            interval_week=interval_week,
            interval_month=interval_month,
            from_date=stockConfig.from_date,
            to_date=stockConfig.to_date
        )
                
        # Выводим отчёт в терминал
        DataCompletenessValidator.print_terminal_report(completeness_report, stockConfig.ticker, stockConfig.interval)

        # Создаем DataFrame с вставленными пропущенными строками
        marked_dataframe = DataCompletenessValidator.insert_missing_intervals_in_dataframe(
            dataframe, completeness_report
        )
        marked_dataframe = interpolate_missing_intervals(marked_dataframe)
        
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
            mode=arguments.anomaly_mode  # удалять аномалии или фикс аномалий
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
        
        # Проверяем полноту данных после обработки аномалий
        verified_completeness_report = DataCompletenessValidator.validate_data_completeness_by_interval(
            df=verified_dataframe,
            interval_secs=interval_sec,
            interval_minutes=interval_minutes,
            interval_hours=interval_hours,
            interval_days=interval_days,
            interval_week=interval_week,
            interval_month=interval_month,
            from_date=stockConfig.from_date,
            to_date=stockConfig.to_date
        )
        
        # Создаем проверенный DataFrame с вставленными пропущенными строками
        marked_verified_dataframe = DataCompletenessValidator.insert_missing_intervals_in_dataframe(
            verified_dataframe, verified_completeness_report
        )
        marked_verified_dataframe = interpolate_missing_intervals(marked_verified_dataframe)
                    
        # Сохраняем проверенный отчёт
        buildReports.one_shore_build_report(
            stockConfig,
            marked_verified_dataframe,
            arguments.destination,
            buildReports.ReportType.VERIFIED_REPORT
        )
        logging.logger.info(
            f"Сохранён проверенный отчёт для {stockConfig.ticker} с {len(verified_dataframe)} свечами"
        )



if __name__ == '__main__':
    asyncio.run(main())