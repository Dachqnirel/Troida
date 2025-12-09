from enum import Enum
from pandas import DataFrame
from packages.API.T_InvestAPI import tAPI
from .dividendConfig import DividendConfig
from pathlib import Path
from datetime import datetime

class DividendReportType(Enum):
    RAW_REPORT = 1          # базовый отчёт по дивидендам
    AGGREGATED_REPORT = 2   # агрегированный отчёт (опционально)

def generate_path_csv(div_config: DividendConfig, directory: str, action: DividendReportType) -> Path:
    """
    Сгенерировать путь для сохранения .csv отчёта по дивидендам.
    """
    if action == DividendReportType.RAW_REPORT:
        base_directory: Path = Path(directory) / "RAW_DIVIDENDS_REPORTS" / "csv"
    else:
        base_directory: Path = Path(directory) / "AGGREGATED_DIVIDENDS_REPORTS" / "csv"

    directory_csv: Path = base_directory / (
        f"{datetime.strftime(div_config.from_date, '%d.%m.%Y %H.%M.%S')} - "
        f"{datetime.strftime(div_config.to_date, '%d.%m.%Y %H.%M.%S')}"
    )

    filename_csv: Path = tAPI._generate_filename(
        div_config.ticker,
        "DIVIDENDS",                # вместо интервала
        div_config.from_date,
        div_config.to_date,
        'csv'
    )
    path_report_csv: Path = directory_csv / filename_csv
    return path_report_csv

def generate_path_parquet(div_config: DividendConfig, directory: str, action: DividendReportType) -> Path:
    """
    Сгенерировать путь для сохранения .parquet отчёта по дивидендам.
    """
    if action == DividendReportType.RAW_REPORT:
        base_directory: Path = Path(directory) / "RAW_DIVIDENDS_REPORTS" / "parquet"
    else:
        base_directory: Path = Path(directory) / "AGGREGATED_DIVIDENDS_REPORTS" / "parquet"

    directory_parquet: Path = base_directory / (
        f"{datetime.strftime(div_config.from_date, '%d.%m.%Y %H.%M.%S')} - "
        f"{datetime.strftime(div_config.to_date, '%d.%m.%Y %H.%M.%S')}"
    )

    filename_parquet: Path = tAPI._generate_filename(
        div_config.ticker,
        "DIVIDENDS",
        div_config.from_date,
        div_config.to_date,
        'parquet'
    )
    path_report_parquet: Path = directory_parquet / filename_parquet
    return path_report_parquet

def one_instrument_build_dividends_report(
    div_config: DividendConfig,
    dividends_df: DataFrame,
    directory: str,
    action: DividendReportType
) -> None:
    """
    Построить отчёт по дивидендам для одного инструмента.
    """
    path_report_csv: Path = generate_path_csv(div_config, directory, action)
    path_report_parquet: Path = generate_path_parquet(div_config, directory, action)

    if not path_report_csv.exists():
        path_report_csv.parent.mkdir(parents=True, exist_ok=True)
    if not path_report_parquet.exists():
        path_report_parquet.parent.mkdir(parents=True, exist_ok=True)

    dividends_df.to_csv(path_report_csv, index=True)
    dividends_df.to_parquet(path_report_parquet, index=True)
