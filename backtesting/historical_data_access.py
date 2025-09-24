import pandas as pd
from datetime import datetime
from pathlib import Path
from backtesting.tickers import tickers
from backtesting.logger_config import setup_logger
import os

logger = setup_logger()


def get_ticker_type(ticker):
    """
    Получение типа тикера (bonds, stocks, currencies, crypto)
    :param symbol: название тикера
    :return: тип тикера (bonds, stocks, currencies, crypto)
    """
    ticker_type = None
    try:
        for key, values in tickers.items():
            if ticker in values:
                ticker_type = key
                break
        if ticker_type is None:
            logger.error(f"Тикер '{ticker}' не найден в базе данных.")
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении типа тикера: {e}")
        return None

    return ticker_type


def get_ticker_data_path(ticker, interval):
    """
    Возвращает путь к файлу с историческими данными
    :param symbol: название тикера
    :param interval: временной интервал (1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo)
    :return: путь к csv файлу или None, если файл не найден
    """

    ticker_type = get_ticker_type(ticker)
    if ticker_type is None:
        return None

    for filename in os.listdir(Path(__file__).parent / f"../historical_data/{ticker_type}/{ticker}"):
        if interval in filename:
            relative_path = Path(__file__).parent / f"../historical_data/{ticker_type}/{ticker}/{filename}"
            absolute_path = relative_path.resolve()
            return absolute_path
    else:
        logger.error(f"Файл с историческими данными для тикера '{ticker}' и интервала '{interval}' не найден.")
        return None


def get_ticker_dataframe(ticker, interval, start_date, end_date):
    """
    Возвращает Dataframe с историческими данными в формте datetime, open, high, low, close, volume
    Принимает любые даты! То есть если файл содержит данные 2010-2020, а вы передали 2015-2017, то вернет данные именно за 2015-2017
    :param symbol: название тикера
    :param interval: временной интервал (1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo)
    :param start_date: начальная дата в формате dd.mm.yy
    :param end_date: конечная дата в формате dd.mm.yy
    :return: объект DataFrame с данными цен в формте datetime, open, high, low, close, volume
    """
    try:
        file_path = get_ticker_data_path(ticker, interval)
        if file_path is None:
            return None

        start_date = datetime.strptime(start_date, "%d.%m.%y")
        end_date = datetime.strptime(end_date, "%d.%m.%y")

        df = pd.read_csv(file_path, sep=",")
        df["datetime"] = pd.to_datetime(df["datetime"])

        df = df[(df["datetime"] >= start_date) & (df["datetime"] <= end_date)]
        df.set_index("datetime", inplace=True, drop=True)

        if df.empty:
            logger.error(f"Для тикера '{ticker}' и интервала '{interval}' нет данных в указанный период! Укажите другие даты в start_date или end_date")
            return None

        return df

    except Exception as e:
        logger.error(f"Ошибка при загрузке данных для тикера '{ticker}': {e}")
        return None



def get_all_tickers(country=None, sector=None):
    """
    Возвращает список тикеров с возможностью фильтрации по стране и/или сектору.

    Параметры:
        country (str, optional): Фильтр по стране (например, "USA")
        sector (str, optional): Фильтр по сектору (например, "Technology")

    Возвращает:
        list: Список отфильтрованных тикеров

    """
    try:
        # Путь к файлу с данными
        csv_path = Path(__file__).parent.parent/ "historical_data" / "tickers_metadata.csv"

        # Чтение CSV-файла
        df = pd.read_csv(csv_path)

        # Применение фильтров
        if country is not None and sector is not None:
            # Фильтрация по стране И сектору
            filtered_df = df[(df['country'].str.lower() == country.lower()) &
                             (df['sector'].str.lower() == sector.lower())]
        elif country is not None:
            # Только по стране
            filtered_df = df[df['country'].str.lower() == country.lower()]
        elif sector is not None:
            # Только по сектору
            filtered_df = df[df['sector'].str.lower() == sector.lower()]
        else:
            # Без фильтров
            filtered_df = df

        # Возвращаем список тикеров
        return filtered_df['ticker'].tolist()

    except FileNotFoundError:
        print("Ошибка: файл tickers_metadata.csv не найден!")
        return []
    except Exception as e:
        print(f"Ошибка при обработке данных: {e}")
        return []
