import asyncio
import os
from datetime import timedelta, datetime, timezone
import pandas as pd
from typing import List, Dict, Optional, Tuple
import glob
import re

from tinkoff.invest import Client, AsyncClient, CandleInterval, InstrumentIdType
from tinkoff.invest.schemas import CandleSource, InstrumentType
from tinkoff.invest.caching.instruments_cache.instruments_cache import InstrumentsCache
from tinkoff.invest.caching.instruments_cache.settings import InstrumentsCacheSettings
from tinkoff.invest.utils import now, quotation_to_decimal, candle_interval_to_timedelta, get_intervals
from tqdm import tqdm
from packages.core import logging
from dotenv import load_dotenv

# Получение токена авторизации из переменных окружения
load_dotenv("./.env")
TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
if not TINKOFF_TOKEN:
    raise ValueError("TINKOFF_TOKEN не задан в переменных окружения")

# Глобальный кэш для избежания повторной загрузки инструментов
_instruments_cache = {} # Быстрый кэш тикер -> instrument
_client = None
_client_service = None
_client_lock = asyncio.Lock()

# Соответствие строковых интервалов enum
_INTERVAL_MAPPING = {
    CandleInterval.CANDLE_INTERVAL_5_SEC: "5S",
    CandleInterval.CANDLE_INTERVAL_10_SEC: "10S",
    CandleInterval.CANDLE_INTERVAL_30_SEC: "30S",
    CandleInterval.CANDLE_INTERVAL_1_MIN: "1M",
    CandleInterval.CANDLE_INTERVAL_2_MIN: "2M",
    CandleInterval.CANDLE_INTERVAL_3_MIN: "3M",
    CandleInterval.CANDLE_INTERVAL_5_MIN: "5M",
    CandleInterval.CANDLE_INTERVAL_10_MIN: "10M",
    CandleInterval.CANDLE_INTERVAL_15_MIN: "15M",
    CandleInterval.CANDLE_INTERVAL_HOUR: "1H",
    CandleInterval.CANDLE_INTERVAL_2_HOUR: "2H",
    CandleInterval.CANDLE_INTERVAL_4_HOUR: "4H",
    CandleInterval.CANDLE_INTERVAL_DAY: "1D",
    CandleInterval.CANDLE_INTERVAL_WEEK: "W",
    CandleInterval.CANDLE_INTERVAL_MONTH: "M"
}

# Обратное соответствие для преобразования строк в enum
_REVERSE_INTERVAL_MAPPING = {v: k for k, v in _INTERVAL_MAPPING.items()}

def _initialize_instruments_cache() -> None:
    """
    Инициализирует кэш инструментов один раз при старте.
    Создает быстрый кэш тикер -> instrument для максимальной производительности.
    """
    
    with Client(TINKOFF_TOKEN) as client:
        cache = InstrumentsCache(
            settings=InstrumentsCacheSettings(), 
            instruments_service=client.instruments,
        )

        # Получаем все типы инструментов
        instrument_sources = [
            cache.shares().instruments,
            cache.bonds().instruments,
            cache.etfs().instruments,
            cache.currencies().instruments,
            cache.futures().instruments,
        ]

        # Фильтрация инструментов
        for instruments in instrument_sources:
            for instrument in instruments:
                ticker = instrument.ticker
                if ticker not in _instruments_cache and \
                        instrument.api_trade_available_flag == True and \
                        instrument.buy_available_flag == True and \
                        instrument.sell_available_flag == True:
                    _instruments_cache[ticker] = instrument

def _get_figi_by_ticker(ticker: str) -> str:
    """
    Получает FIGI инструмента по тикеру с максимальной производительностью.
    Использует предварительно построенный кэш.
    
    Args:
        ticker (str): Тикер инструмента
        
    Returns:
        str: FIGI инструмента
        
    Raises:
        ValueError: Если инструмент с указанным тикером не найден
    """
    # Инициализируем кэш при первом вызове
    if not _instruments_cache:
        _initialize_instruments_cache()
    
    if ticker in _instruments_cache:
        return _instruments_cache[ticker].figi
    
    raise ValueError(f"Инструмент с тикером '{ticker}' не найден")

async def _get_client() -> AsyncClient:
    """
    Возвращает глобальный асинхронный клиент, инициализируя его при необходимости.
    
    Returns:
        AsyncClient: Глобальный асинхронный клиент
    """

    global _client, _client_service

    async with _client_lock:
        if _client_service is None or _client is None:
            _client_service = AsyncClient(TINKOFF_TOKEN)
            _client = await _client_service.__aenter__()

    return _client

async def _close_client():
    """
    Закрывает глобальный асинхронный клиент.
    """
    global _client, _client_service

    async with _client_lock:
        if _client_service is not None and _client is not None:
            await _client_service.__aexit__(None, None, None)
            _client = None

def _interval_to_string(interval: CandleInterval) -> str:
    """
    Преобразует интервал свечей в строковое представление для использования в именах файлов.
    
    Args:
        interval (CandleInterval): Интервал свечей из Tinkoff API
        
    Returns:
        str: Строковое представление интервала
    """

    return _INTERVAL_MAPPING.get(interval, str(interval))

def _generate_filename(ticker: str, interval: CandleInterval, start_date: datetime, end_date: datetime, format: str) -> str:
    """
    Генерирует имя файла для сохранения данных свечей.
    
    Args:
        ticker (str): Тикер инструмента
        interval (CandleInterval): Интервал свечей
        start_date (datetime): Начальная дата периода
        end_date (datetime): Конечная дата периода
        
    Returns:
        str: Имя файла в формате: {тикер}_{интервал}_{начальная_дата}_{конечная_дата}.{формат} (csv, parquet)
    """
    start_str = start_date.strftime("%Y%m%d_%H%M%S")
    end_str = end_date.strftime("%Y%m%d_%H%M%S")
    return f"{ticker}_{_interval_to_string(interval)}_{start_str}_{end_str}.{format}"

def _find_existing_file(ticker: str, interval: CandleInterval, format: str) -> Optional[str]:
    """
    Ищет существующий файл с данными для указанного тикера и интервала.
    
    Args:
        ticker (str): Тикер инструмента
        interval (CandleInterval): Интервал свечей
        
    Returns:
        Optional[str]: Путь к найденному файлу или None, если файл не найден
    """
    pattern = f"{ticker}_{_interval_to_string(interval)}_*.{format}"
    files = glob.glob(pattern)
    return files[0] if files else None

def _parse_dates_from_filename(filename: str, interval: CandleInterval) -> Tuple[datetime, datetime]:
    """
    Извлекает даты начала и конца периода из имени файла.
    
    Args:
        filename (str): Имя файла
        interval (CandleInterval): Интервал свечей (не используется, но оставлен для совместимости)
        
    Returns:
        Tuple[datetime, datetime]: Кортеж (начальная_дата, конечная_дата)
    """
    parts = filename.replace('.csv', '').replace('.parquet', '').split('_')
    start_date = datetime.strptime(f"{parts[-4]}_{parts[-3]}", "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    end_date = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    return start_date, end_date

def _extract_wait_time_from_error(error) -> int:
    """
    Возвращает сколько секунд подождать до сброса лимита.
    """
    m = re.search(r'ratelimit_reset=(\d+)', str(error))
    if not m:
        return 10
    reset_ts = int(m.group(1))          # epoch seconds
    now_ts = int(datetime.now(timezone.utc).timestamp())
    wait = max(1, reset_ts - now_ts)    # подождать до будущего момента
    return wait

async def download_candles(ticker: str, interval: str, from_date: datetime, to_date: datetime) -> Optional[pd.DataFrame]:
    """
    Загружает исторические данные свечей с Tinkoff API.
    
    Args:
        ticker (str): Тикер инструмента
        interval (str): Интервал свечей
        from_date (datetime): Начальная дата периода
        to_date (datetime): Конечная дата периода
        
    Returns:
        pd.DataFrame: DataFrame с данными свечей, индексированный по дате
    """
    interval = _REVERSE_INTERVAL_MAPPING.get(interval, None)
    if interval is None:
        return None

    figi = _get_figi_by_ticker(ticker)
    logging.logger.info(f'figi {figi}')
    all_candles_data = []

    client = await _get_client()

    intervals = list(get_intervals(interval, from_date, to_date))

    # Загружаем свечи с прогресс-баром
    for local_from, local_to in tqdm(iterable=intervals, total=len(intervals), desc=f"Загрузка данных {ticker}", unit=" промежутков"):
        while True:
            try:
                # Используем get_candles вместо get_all_candles            
                response = await client.market_data.get_candles(
                    figi=figi,
                    from_=local_from,
                    to=local_to,
                    interval=interval,
                    candle_source_type=CandleSource.CANDLE_SOURCE_INCLUDE_WEEKEND,
                )
                break
            
            except Exception as e:
                # Обрабатываем ограничение запросов
                if 'RESOURCE_EXHAUSTED' in str(e) or 'ratelimit' in str(e).lower():
                    wait_time = _extract_wait_time_from_error(e)
                    print(f"{ticker}: Ждем {wait_time} сек...")
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(10)

        # Обрабатываем полученные свечи
        local_candles_data = [
            (candle.time,
            float(quotation_to_decimal(candle.open)),
            float(quotation_to_decimal(candle.high)),
            float(quotation_to_decimal(candle.low)),
            float(quotation_to_decimal(candle.close)),
            candle.volume)
            for candle in response.candles
        ]

        # Добавляем свечи в общий массив
        all_candles_data.extend(local_candles_data)

    if len(all_candles_data) > 0:
        # Создаем DataFrame и настраиваем индекс
        df = pd.DataFrame(all_candles_data, columns=["datetime", "open", "high", "low", "close", "volume"])
        if not df.empty:
            df['datetime'] = pd.to_datetime(df['datetime'])
        return df

    return None

def _load_dataframe(filename: str) -> Optional[pd.DataFrame]:
    """
    Загружает DataFrame из файла в зависимости от формата.
    
    Args:
        filename (str): Имя файла
        
    Returns:
        pd.DataFrame: Загруженный DataFrame
    """
    try:    
        if filename.endswith('.parquet'):
            return pd.read_parquet(filename)
        elif filename.endswith('.csv'):
            return pd.read_csv(filename)
        else:
            return None
    except Exception as e:
        print(f"Ошибка при чтении файла {filename}: {e}")
        return None

def _save_dataframe(df: pd.DataFrame, filename: str):
    """
    Сохраняет DataFrame в файл в зависимости от формата.
    
    Args:
        df (pd.DataFrame): DataFrame для сохранения
        filename (str): Имя файла
    """
    try:
        if filename.endswith('.parquet'):
            df.to_parquet(filename, index=True, compression="zstd")
        elif filename.endswith('.csv'):
            df.to_csv(filename, index=True)
        else:
            raise Exception(f"Получен файл с неподходящим форматом")
    except Exception as e:
        print(f"Ошибка при сохранении файла {filename}: {e}")

async def load_candles_local(ticker: str, interval: str, from_date: datetime, to_date: datetime, format: str = "csv") -> Optional[pd.DataFrame]:
    """
    Загружает данные свечей только из локального файла без обращения к API.
    
    Args:
        ticker (str): Тикер инструмента
        interval (str): Интервал свечей
        from_date (datetime): Начальная дата периода
        to_date (datetime): Конечная дата периода
        format (str): Формат файла датафрейма (csv, parquet)

    Returns:
        Optional[pd.DataFrame]: DataFrame с данными или None, если файл не найден
    """
    # Ищем существующий файл с данными
    existing_file = _find_existing_file(ticker, interval, format)
    if existing_file is None:
        return None

    df_existing = _load_dataframe(existing_file)
    if df_existing is None:
        return None
    
    df_existing['datetime'] = pd.to_datetime(df_existing['datetime'])

    # ОБРЕЗАЕМ данные по запрошенному диапазону
    df_existing = df_existing[
        (df_existing["datetime"] >= from_date) & 
        (df_existing["datetime"] <= to_date)
    ]

    return df_existing

async def load_candles(ticker: str, interval: str, from_date: datetime, to_date: datetime, format: str = "csv") -> Optional[pd.DataFrame]:
    """
    Основная функция для загрузки данных свечей.
    
    Комбинирует локальные данные с загрузкой недостающих данных через API.
    Автоматически обновляет локальные файлы при необходимости.
    
    Args:
        ticker (str): Тикер инструмента
        interval (str): Интервал свечей
        from_date (datetime): Начальная дата периода
        to_date (datetime): Конечная дата периода
        format (str): Формат файла датафрейма (csv, parquet)
        
    Returns:
        Optional[pd.DataFrame]: DataFrame с данными свечей или None при ошибке
    """
    # Ищем существующий файл с данными
    existing_file = _find_existing_file(ticker, interval, format)

    # Если файл не существует, загружаем полностью новые данные
    if existing_file is None:
        df_new = await download_candles(ticker, interval, from_date, to_date)
        if not df_new.empty:
            start, end = df_new["datetime"].min(), df_new["datetime"].max()
            _save_dataframe(df_new, _generate_filename(ticker, interval, start, end, format))
            return df_new

    all_data_parts = []

    # Загружаем существующие данные
    df_existing = _load_dataframe(existing_file)
    if df_existing is None:
        return None

    df_existing['datetime'] = pd.to_datetime(df_existing['datetime'])
    old_start_date, old_end_date = _parse_dates_from_filename(existing_file, interval)
    
    # Проверяем, нужны ли дополнительные данные слева или справа
    need_left = from_date < old_start_date
    need_right = to_date > old_end_date

    # Если все данные уже есть в файле, просто фильтруем
    if not need_left and not need_right:
        result_df = df_existing[(df_existing["datetime"] >= from_date) & (df_existing["datetime"] <= to_date)]
        return result_df

    all_data_parts.append(df_existing)

    # Загружаем недостающие данные слева
    if need_left:
        df_left = await download_candles(ticker, interval, from_date, old_start_date)
        if df_left is not None:
            all_data_parts.insert(0, df_left)

    # Загружаем недостающие данные справа
    if need_right:
        df_right = await download_candles(ticker, interval, old_end_date, to_date)
        if df_right is not None:
            all_data_parts.append(df_right)

    # Объединяем все части данных
    df_combined = pd.concat(all_data_parts)
    # Удаляем дубликаты по индексу (дата/время)
    df_combined = df_combined[~df_combined["datetime"].duplicated(keep='first')]
    df_combined = df_combined.sort_index()
    
    # Сохраняем обновленный файл
    new_start, new_end = df_combined["datetime"].min(), df_combined["datetime"].max()
    os.remove(existing_file)
    _save_dataframe(df_combined, _generate_filename(ticker, interval, new_start, new_end, format))
    
    # Возвращаем запрошенный диапазон
    result_df = df_combined[(df_combined["datetime"] >= from_date) & (df_combined["datetime"] <= to_date)]
    return result_df

async def load_multiple_candles(instruments: List[Dict], max_concurrent: int=2) -> Dict[str, pd.DataFrame]:
    """
    Загружает данные для нескольких инструментов параллельно.
    
    Args:
        instruments (List[Dict]): Список словарей с параметрами для каждого инструмента.
                                 Каждый словарь должен содержать ключи: 
                                 ticker, interval, from_date, to_date, format
        max_concurrent (int): Максимальное количество одновременных запросов
        
    Returns:
        Dict[str, pd.DataFrame]: Словарь с тикерами в качестве ключей и DataFrame в качестве значений
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process(instrument):
        """Обрабатывает загрузку данных для одного инструмента"""
        async with semaphore:
            try:
                df = await load_candles(**instrument)
                return instrument['ticker'], df
            except Exception as e:
                print(f"Ошибка {instrument['ticker']}: {e}")
                return instrument['ticker'], None

    # Запускаем параллельную обработку всех инструментов
    results = await asyncio.gather(*(process(inst) for inst in instruments))
    # Фильтруем успешные результаты
    return {ticker: df for ticker, df in results if df is not None and not df.empty} 

# async def main(): 
#     TO_DATE = datetime.now(timezone.utc) 
#     FROM_DATE = TO_DATE - timedelta(days=28) 
#     df = await load_multiple_candles( instruments=[ {'ticker': "YDEX", 'interval': '5S', 'from_date': FROM_DATE, 'to_date': TO_DATE, 'format': 'parquet'}, {'ticker': "VTBR", 'interval': '5S', 'from_date': FROM_DATE, 'to_date': TO_DATE, 'format': 'parquet'}, {'ticker': "GMKN", 'interval': '5S', 'from_date': FROM_DATE, 'to_date': TO_DATE, 'format': 'parquet'}, ], max_concurrent=3, ) 
#     await _close_client() 
    
# if __name__ == "__main__": 
#     import asyncio 
#     asyncio.run(main())