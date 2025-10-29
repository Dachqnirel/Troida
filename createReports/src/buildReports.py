from enum import Enum
from pandas import DataFrame
from packages.API.T_InvestAPI import tAPI
from .stockConfig import StockConfig
from pathlib import Path
from datetime import datetime, timezone


class ReportType(Enum):
    VERIFIED_REPORT = 1, # проверенный на аномалии отчёт
    UNVERIFIED_REPORT = 2 # непроверенный на аномалии отчёт
    
    
def generate_path_csv(shore_config: StockConfig, directory: str, action: ReportType) -> Path:
    """
    Сгенерировать путь для сохранения .csv отчёта

    Args:
        shore_config (StockConfig): краткая характеристика акции: тикер, интервал свечей, дата начала и дата конца
        directory (str): директория для сохранения отчётов
        action (ReportType): тип отчёта: проверенный на аномалии или непроверенный на аномалии

    Returns:
        Path: путь для записи .csv файла
    """    
    if action == ReportType.UNVERIFIED_REPORT:
        base_directory: Path = Path(directory) / "UNVERIFIED_REPORTS_SHORES" / "сsv"
        
        directory_csv: Path = base_directory / f"{datetime.strftime(shore_config.from_date, '%d.%m.%Y %H.%M.%S')} - {datetime.strftime(shore_config.to_date, '%d.%m.%Y %H.%M.%S')}"
        filename_csv: Path =  tAPI._generate_filename(shore_config.ticker,
                                                shore_config.interval,
                                                shore_config.from_date,
                                                shore_config.to_date,
                                                'csv')
        path_report_csv: Path = directory_csv / filename_csv
        return path_report_csv
    if action == ReportType.VERIFIED_REPORT:
        base_directory: Path = Path(directory) / "VERIFIED_REPORTS_SHORES" / "сsv"
        directory_csv: Path = base_directory / f"{datetime.strftime(shore_config.from_date, '%d.%m.%Y %H.%M.%S')} - {datetime.strftime(shore_config.to_date, '%d.%m.%Y %H.%M.%S')}"
        filename_csv: Path = tAPI._generate_filename(shore_config.ticker,
                                                shore_config.interval,
                                                shore_config.from_date,
                                                shore_config.to_date,
                                                'csv')
        path_report_csv: Path = directory_csv / filename_csv
        return path_report_csv
    
    
def generate_path_parquit(shore_config: StockConfig, directory: str, action: ReportType) -> Path:
    """
    Генерация отчёта для .parquit

    Args:
        shore_config (StockConfig): краткая характеристика акции: тикер, интервал свечей, дата начала и дата конца
        directory (str): директория для сохранения отчётов
        action (ReportType): тип отчёта: проверенный на аномалии или непроверенный на аномалии

    Returns:
        Path: путь для записи .parquit файла
    """    
    if action == ReportType.UNVERIFIED_REPORT:
        base_directory: Path = Path(directory) / "UNVERIFIED_REPORTS_SHORES" / "parquit"

        directory_parquit: Path = base_directory / f"{datetime.strftime(shore_config.from_date, '%d.%m.%Y %H.%M.%S')} - {datetime.strftime(shore_config.to_date, '%d.%m.%Y %H.%M.%S')}"
        filename_parquit: Path = tAPI._generate_filename(shore_config.ticker,
                                                shore_config.interval,
                                                shore_config.from_date,
                                                shore_config.to_date,
                                                'parquit')
        path_report_parquit: Path = directory_parquit / filename_parquit
        return path_report_parquit
    if action == ReportType.VERIFIED_REPORT:
        base_directory: Path = path_report_parquit / "VERIFIED_REPORTS_SHORES" / "parquit"
        directory_parquit: Path = base_directory / f"{datetime.strftime(shore_config.from_date, '%d.%m.%Y %H.%M.%S')} - {datetime.strftime(shore_config.to_date, '%d.%m.%Y %H.%M.%S')}"
        filename_parquit: Path = tAPI._generate_filename(shore_config.ticker,
                                                shore_config.interval,
                                                shore_config.from_date,
                                                shore_config.to_date,
                                                'parquit')
        path_report_parquit: Path = directory_parquit / filename_parquit
        return path_report_parquit




def one_shore_build_report(shore_config: StockConfig, candles: DataFrame, directory: str, action: ReportType) -> None:
    """
    Построить отчёт по одной акции. Наименование и характеристики акции берутся из класса StockConfig,
    свечи берутся из класса DataFrame.

    Args:
        shore_config (StockConfig): конфигурация акции: тикер, интервалы, от какой даты считывание и до какой даты считывание
        candles (DataFrame): датафрейм свечей
        directory (str): путь для сохранения отчёта (без наименования файла)
        action (ReportType): тип отчёта: проверенный на аномалии или непроверенный на аномалии
    """    
    path_report_csv: Path = generate_path_csv(shore_config, directory, action)
    path_report_parquit: Path = generate_path_parquit(shore_config, directory, action)
    
    if not path_report_csv.exists():
        path_report_csv.parent.mkdir(parents=True, exist_ok=True)
    
    if not path_report_parquit.exists():
        path_report_parquit.parent.mkdir(parents=True, exist_ok=True)
    
    candles.to_csv(path_report_csv, index=True)
    candles.to_parquet(path_report_parquit, index=True)
        