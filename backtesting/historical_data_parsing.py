import time
import yfinance as yf
from dateutil import parser
import os
from pathlib import Path
import time
from datetime import date, datetime, timedelta
from historical_data_access import get_ticker_type
from tickers import tickers
import pandas as pd



def format_yfinance_ticker(ticker: str, ticker_type: str) -> str:
    """
    Форматирует тикер для корректной загрузки данных через Yahoo Finance.

    :param ticker: оригинальный тикер из базы данных
    :param ticker_type: тип актива (stocks/currencies/crypto)
    :return: тикер в формате, распознаваемом Yahoo Finance
    """
    if ticker_type == "currencies":
        # Для валютных пар: добавляем суффикс =X если его нет (EURUSD → EURUSD=X)
        return f"{ticker}=X" if "=X" not in ticker else ticker
    elif ticker_type == "crypto":
        # Для криптовалют: добавляем - если нет дефиса (BTCUSD → BTC-USD)
        return f"{ticker[:-3]}-{ticker[-3:]}" if "-" not in ticker else ticker
    else:
        # Для акций и других типов оставляем без изменений
        return ticker


def download_ticker_data(ticker, interval, start_date, end_date=None):
    """
    Скачивает данные по тикеру и сохраняет их в csv файл
    :param ticker: название тикера
    :param interval: временной интервал (1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo)
    :param start_date: начальная дата в формате dd.mm.yy
    :param end_date: конечная дата в формате dd.mm.yy
    :return: True, если данные успешно сохранены, иначе False
    """
    try:
        base_dir = Path(__file__).parent.parent
        ticker_type = get_ticker_type(ticker)
        ticker_name = format_yfinance_ticker(ticker, ticker_type)
        folder_path = base_dir / "historical_data" / ticker_type / ticker
        folder_path.mkdir(parents=True, exist_ok=True)
        df = yf.download(
            ticker_name,
            interval=interval,
            start=parser.parse(start_date, dayfirst=True),
            end=parser.parse(end_date, dayfirst=True) if end_date else None,
            progress=False,
            ignore_tz=True,
            auto_adjust=True,
            group_by="ticker",
        )
        if df.empty:
            print(f"⚠️ Нет данных для {ticker_name} ({interval})")
            return False
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(0, axis=1)
        df.reset_index(inplace=True)
        column_mapping = {
            "Datetime": "datetime",
            "Date": "datetime",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Adj Close": "adj_close",
        }
        df.rename(
            columns={k: v for k, v in column_mapping.items() if k in df.columns},
            inplace=True,
        )
        start_fmt = parser.parse(start_date, dayfirst=True).strftime("%Y%m%d")
        end_fmt = (
            parser.parse(end_date, dayfirst=True).strftime("%Y%m%d")
            if end_date
            else "now"
        )
        file_name = f"{ticker}_{interval}_{start_fmt}_{end_fmt}.csv"
        full_path = folder_path / file_name
        cols_to_save = [
            col
            for col in [
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "adj_close",
            ]
            if col in df.columns
        ]
        df[cols_to_save].to_csv(full_path, index=False, date_format="%Y-%m-%d %H:%M:%S")
        print(f"✅ Данные сохранены: {full_path}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при обработке {ticker_name}: {str(e)}")
        return False


def download_all_tickers(start_date, end_date):
    """
    Запускает процесс загрузки данных по всем тикерам из словаря tickers.py
    :param start_date: начальная дата в формате dd.mm.yy
    :param end_date: конечная дата в формате dd.mm.yy
    :return: None
    """
    current_date = datetime.now()
    start_dt = parser.parse(start_date, dayfirst=True)
    end_dt = parser.parse(end_date, dayfirst=True)
    LIMITS = {
        "15m": {"max_days": 59, "delta": timedelta(days=59)},
        "1h": {"max_days": 729, "delta": timedelta(days=729)},
        "1d": {"max_days": None},
    }
    for ticker_type, ticker_list in tickers.items():
        for ticker in ticker_list:

            for interval, limit in LIMITS.items():
                print(f"\n{'=' * 50}\nОбработка {ticker} ({interval})")
                if not limit["max_days"]:
                    try:

                        download_ticker_data(ticker, interval, start_date, end_date)
                        print(f"✅ {ticker} ({interval}): Полная история загружена")
                        time.sleep(1)
                        continue
                    except Exception as e:
                        print(f"❌ Критическая ошибка: {e}")
                        continue
                earliest_date = current_date - timedelta(days=limit["max_days"])
                actual_start = max(start_dt, earliest_date)
                actual_end = min(end_dt, current_date)
                if actual_start >= actual_end:
                    if start_dt < earliest_date:
                        print(f"⚠️ Внимание! {ticker} ({interval}):")
                        print(
                            f"Исторические данные доступны только с {earliest_date.strftime('%d.%m.%Y')}"
                        )
                        print(
                            f"Ваш запрос: с {start_dt.strftime('%d.%m.%Y')} по {end_dt.strftime('%d.%m.%Y')}"
                        )
                    else:
                        print(f"⏩ Нет новых данных для загрузки")
                    continue
                if interval == "15m":
                    print("🔄 Загружаю 15-минутные данные частями:")
                    chunk_start = actual_start
                    chunk_num = 1

                    while chunk_start < actual_end:
                        chunk_end = min(chunk_start + limit["delta"], actual_end)

                        try:
                            print(
                                f"\nЧасть {chunk_num}: {chunk_start.date()} - {chunk_end.date()}"
                            )
                            download_ticker_data(
                                ticker,
                                "15m",
                                chunk_start.strftime("%d.%m.%Y"),
                                chunk_end.strftime("%d.%m.%Y"),
                            )
                            print(f"✅ Успешно сохранено")
                        except Exception as e:
                            print(f"❌ Ошибка загрузки: {e}")
                            break

                        chunk_start = chunk_end + timedelta(days=1)
                        chunk_num += 1
                        time.sleep(1)
                else:
                    try:
                        print(
                            f"⬇️ Загружаю {interval} данные: {actual_start.date()} - {actual_end.date()}"
                        )
                        download_ticker_data(
                            ticker,
                            interval,
                            actual_start.strftime("%d.%m.%Y"),
                            actual_end.strftime("%d.%m.%Y"),
                        )
                        print(f"✅ Успешно сохранено")
                    except Exception as e:
                        print(f"❌ Ошибка загрузки: {e}")

                time.sleep(1)

    print("\n⭐ Все операции завершены! Проверьте логи.")


import os
import requests
from pathlib import Path
import pandas as pd
import time
from typing import Optional
from datetime import datetime, timedelta

MOEX_TICKERS = [
    "SBER",
    "GAZP",
    "LKOH",
    "MGNT",
    "ROSN",
    "NVTK",
    "TATN",
    "YNDX",
    "PLZL",
    "ALRS",
    "MOEX",
    "SBERP",
    "GMKN",
    "MTSS",
    "AFKS",
    "PHOR",
    "RUAL",
    "SNGS",
    "SNGSP",
    "VTBR",
]

BASE_DIR = Path(__file__).parent.parent / "historical_data" / "moex"
BASE_DIR.mkdir(parents=True, exist_ok=True)

INTERVAL_MAPPING = {"15m": 15, "1h": 60, "1d": 24}


def save_data(
    ticker: str, df: pd.DataFrame, interval: str, start_date: str, end_date: str
) -> bool:
    """Сохраняет данные в CSV файл."""
    try:
        ticker_dir = BASE_DIR / ticker
        ticker_dir.mkdir(exist_ok=True)

        filename = f"{ticker}_{interval}_{start_date.replace('-', '')}_{end_date.replace('-', '')}.csv"
        filepath = ticker_dir / filename

        df.to_csv(filepath, index=False)
        print(f"✅ Данные сохранены: {filepath}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении данных {ticker}: {e}")
        return False


def get_moex_candles(
    ticker: str, start_date: str, end_date: str, interval: int
) -> Optional[pd.DataFrame]:
    """Получает данные свечей напрямую из API MOEX"""
    try:
        url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
        params = {"from": start_date, "till": end_date, "interval": interval}

        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        if not data["candles"]["data"]:
            return None

        df = pd.DataFrame(data["candles"]["data"])
        df.columns = data["candles"]["columns"]

        # Стандартизируем колонки
        df = df.rename(
            columns={
                "begin": "datetime",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
        )

        return df[["datetime", "open", "high", "low", "close", "volume"]]

    except Exception as e:
        print(f"⚠️ Ошибка при загрузке данных {ticker}: {e}")
        return None


def download_ticker_data2(ticker: str, interval: str, start_date: str, end_date: str):
    """Загружает данные для конкретного тикера и интервала"""
    print(f"\nЗагрузка {ticker} ({interval}) с {start_date} по {end_date}")

    interval_value = INTERVAL_MAPPING[interval]

    # Для внутридневных данных разбиваем на месячные интервалы
    if interval != "1d":
        current_start = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        while current_start < end_dt:
            current_end = current_start + timedelta(days=30)
            current_end = min(current_end, end_dt)

            print(f"Период: {current_start.date()} - {current_end.date()}")

            df = get_moex_candles(
                ticker,
                current_start.strftime("%Y-%m-%d"),
                current_end.strftime("%Y-%m-%d"),
                interval_value,
            )

            if df is not None:
                save_data(
                    ticker,
                    df,
                    interval,
                    current_start.strftime("%Y-%m-%d"),
                    current_end.strftime("%Y-%m-%d"),
                )

            current_start = current_end + timedelta(days=1)
            time.sleep(2)
    else:
        # Для дневных данных загружаем весь период
        df = get_moex_candles(ticker, start_date, end_date, interval_value)
        if df is not None:
            save_data(ticker, df, interval, start_date, end_date)


def download_all_tickers2():
    """Загружает данные для всех тикеров и интервалов"""
    start_date = "2020-01-01"
    end_date = "2024-01-01"

    for ticker in MOEX_TICKERS:
        for interval in INTERVAL_MAPPING.keys():
            download_ticker_data2(ticker, interval, start_date, end_date)
            time.sleep(1)


def download_all_tickers3():
    tickers = [
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", 
    "TSLA", "BRK.B", "NVDA", "JPM", "JNJ", 
    "V", "PG", "UNH", "HD", "MA", 
    "DIS", "PYPL", "BAC", "INTC", "CRM", 
    "XOM", "PFE", "VZ", "ABT", "KO", 
    "T", "NFLX", "ADBE", "CSCO", "PEP", 
    "MRK", "WMT", "ABBV", "CVX", "MCD", 
    "COST", "NKE", "AMD", "TMO", "UPS", 
    "LIN", "ORCL", "IBM", "QCOM", "TXN", 
    "DHR", "PM", "NEE", "LOW", "HON", 
    "SBUX", "AMGN", "MDT", "BMY", "INTU", 
    "BLK", "GS", "AXP", "CAT", "DE"
    ]
    interval = "1d"
    start_date = datetime(2015, 1, 1)
    end_date = datetime.now()
    for ticker in tickers:
        print(f"\n{'=' * 50}")
        print(f"Начинаем загрузку данных для {ticker}")
        print(f"{'=' * 50}")
        download_stock_data(ticker, interval, start_date, end_date)


def download_stock_data(ticker, interval, start_date, end_date):
    # Данные по акциям за 10 лет с интервалом 1 день
    output_file = f"{ticker}_Prices.csv"
    if os.path.exists(output_file):
        os.remove(output_file)
        print(f"Старый файл {output_file} удален")
    all_data = pd.DataFrame()
    current_start = start_date
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=4000), end_date)
        print(
            f"[{ticker}] Загружаем данные с {current_start.date()} по {current_end.date()}"
        )
        try:
            data = yf.download(
                ticker,
                start=current_start,
                end=current_end,
                interval=interval,
                progress=False,
            )
            if not data.empty:
                if "Adj Close" in data.columns:
                    data.drop("Adj Close", axis=1, inplace=True)
                data.rename(
                    columns={
                        "Datetime": "datetime",
                        "Date": "datetime",
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume",
                    }
                )
                all_data = pd.concat([all_data, data])
                print(
                    f"[{ticker}] Успешно загружены данные за {current_start.date()} - {current_end.date()}"
                )
            else:
                print(
                    f"[{ticker}] Нет данных за период {current_start.date()} - {current_end.date()}"
                )
        except Exception as e:
            print(f"[{ticker}] Ошибка при загрузке данных: {e}")
            time.sleep(10)
        current_start = current_end
    if not all_data.empty:
        save_data(ticker, all_data, "1d", start_date, end_date)
    else:
        print(f"\n[{ticker}] Не удалось загрузить данные\n")


download_all_tickers("01.01.21", "28.03.25")