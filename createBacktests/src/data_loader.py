from pathlib import Path

import pandas as pd

from src.config import DataConfig


def _normalize_format(data_path: Path, configured_format: str) -> str:
    file_format = configured_format.lower().strip()
    if file_format:
        return "parquet" if file_format == "parquit" else file_format

    suffix = data_path.suffix.lower().lstrip(".")
    return "parquet" if suffix == "parquit" else suffix


def _read_dataframe(data_path: Path, file_format: str) -> pd.DataFrame:
    if file_format == "csv":
        return pd.read_csv(data_path)
    if file_format == "parquet":
        return pd.read_parquet(data_path)

    raise ValueError(
        f"Неподдерживаемый формат данных '{file_format}'. "
        "Используйте csv или parquet."
    )


def load_market_data(config: DataConfig) -> pd.DataFrame:
    data_path = config.path.expanduser().resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"Файл с данными не найден: {data_path}")

    file_format = _normalize_format(data_path, config.format)
    dataframe = _read_dataframe(data_path, file_format)
    dataframe.columns = [str(column).strip().lower() for column in dataframe.columns]

    unnamed_columns = [column for column in dataframe.columns if column.startswith("unnamed:")]
    if unnamed_columns:
        dataframe = dataframe.drop(columns=unnamed_columns)

    if "datetime" not in dataframe.columns and dataframe.index.name == "datetime":
        dataframe = dataframe.reset_index()

    if "datetime" not in dataframe.columns:
        raise ValueError("В файле нет колонки 'datetime', необходимой для backtrader.")

    if config.drop_non_present_bars and "data_status" in dataframe.columns:
        dataframe = dataframe[dataframe["data_status"].fillna("present") == "present"]

    required_columns = ("open", "high", "low", "close")
    for column in required_columns:
        if column not in dataframe.columns:
            raise ValueError(f"В файле отсутствует обязательная колонка '{column}'.")

    if "volume" not in dataframe.columns:
        dataframe["volume"] = 0.0

    dataframe["datetime"] = pd.to_datetime(dataframe["datetime"], utc=True, errors="coerce")
    dataframe = dataframe.dropna(subset=["datetime"])

    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")

    dataframe = dataframe.dropna(subset=["open", "high", "low", "close"])
    dataframe["openinterest"] = 0.0
    dataframe["datetime"] = dataframe["datetime"].dt.tz_localize(None)
    dataframe = dataframe.sort_values("datetime").drop_duplicates(subset=["datetime"])
    dataframe = dataframe.set_index("datetime")

    prepared = dataframe[["open", "high", "low", "close", "volume", "openinterest"]]
    if prepared.empty:
        raise ValueError("После подготовки данных не осталось ни одной свечи для бэктеста.")

    return prepared
