import asyncio
import os
from datetime import timedelta, datetime, timezone
import pandas as pd
from typing import List, Dict, Optional, Tuple
import glob
import re
from dotenv import load_dotenv
from tinkoff.invest import AsyncClient, CandleInterval
from tinkoff.invest.services import InstrumentsService
from tinkoff.invest.schemas import CandleSource, InstrumentType
from tinkoff.invest.utils import now, quotation_to_decimal, candle_interval_to_timedelta
from .caches import _INSTRUMENTS_CACHE, semaphoreForAccessCache
from ..logging import *
import packages.initial_setup as initial_setup

# Получение токена авторизации из переменных окружения
load_dotenv()
TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
if not TINKOFF_TOKEN:
    raise ValueError("TINKOFF_TOKEN не задан в переменных окружения")


def _interval_to_string(interval: CandleInterval) -> str:
    """
    Преобразует интервал свечей в строковое представление для использования в именах файлов.
    
    Args:
        interval (CandleInterval): Интервал свечей из Tinkoff API
        
    Returns:
        str: Строковое представление интервала
    """
    mapping = {
        CandleInterval.CANDLE_INTERVAL_5_SEC: "5S",
        CandleInterval.CANDLE_INTERVAL_10_SEC: "15S",
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
        CandleInterval.CANDLE_INTERVAL_WEEK: "1W",
        CandleInterval.CANDLE_INTERVAL_MONTH: "1MON"
    }
    return mapping.get(interval, str(interval))

def _generate_filename(ticker: str, interval: CandleInterval, start_date: datetime, end_date: datetime) -> str:
    logger.debug(f'start_date = {start_date}\tend_date = {end_date}')
    """
    Генерирует имя файла для сохранения данных свечей.
    
    Args:
        ticker (str): Тикер инструмента
        interval (CandleInterval): Интервал свечей
        start_date (datetime): Начальная дата периода
        end_date (datetime): Конечная дата периода
        
    Returns:
        str: Имя файла в формате: {тикер}_{интервал}_{начальная_дата}_{конечная_дата}.csv
    """
    start_str = start_date.strftime("%Y%m%d_%H%M%S")
    end_str = end_date.strftime("%Y%m%d_%H%M%S")
    return f"{ticker}_{_interval_to_string(interval)}_{start_str}_{end_str}.csv"

def _find_existing_file(ticker: str, interval: CandleInterval, directory: initial_setup.Path) -> Optional[str]:
    """
    Ищет существующий файл с данными для указанного тикера и интервала.
    
    Args:
        ticker (str): Тикер инструмента
        interval (CandleInterval): Интервал свечей
        
    Returns:
        Optional[str]: Путь к найденному файлу или None, если файл не найден
    """
    pattern: initial_setup.Path = str(directory / f"{ticker}_{_interval_to_string(interval)}_*.csv")
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
    parts = filename.replace('.csv', '').split('_')
    start_date = datetime.strptime(f"{parts[-4]}_{parts[-3]}", "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    end_date = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    return start_date, end_date

async def _get_figi_by_ticker(ticker: str, instrument_type: InstrumentType) -> str:
    """
    Получает FIGI инструмента по его тикеру и типу.
    
    Args:
        ticker (str): Тикер инструмента
        instrument_type (InstrumentType): Тип инструмента (акция, облигация, etc.)
        
    Returns:
        str: FIGI инструмента
        
    Raises:
        ValueError: Если инструмент с указанным тикером не найден
    """
    async with AsyncClient(TINKOFF_TOKEN) as client:
        # Получаем список инструментов в зависимости от типа
        getInstrumentsFunctions: InstrumentsService = client.instruments
        async with semaphoreForAccessCache:
            if instrument_type not in _INSTRUMENTS_CACHE:
                match instrument_type:
                    case  InstrumentType.INSTRUMENT_TYPE_SHARE:
                        _INSTRUMENTS_CACHE[instrument_type] = await getInstrumentsFunctions.shares()
                    case  InstrumentType.INSTRUMENT_TYPE_BOND:
                        _INSTRUMENTS_CACHE[instrument_type] = await getInstrumentsFunctions.bonds()
                    case InstrumentType.INSTRUMENT_TYPE_ETF:
                        _INSTRUMENTS_CACHE[instrument_type] = await getInstrumentsFunctions.etfs()
                    case InstrumentType.INSTRUMENT_TYPE_CURRENCY:
                        _INSTRUMENTS_CACHE[instrument_type] = await getInstrumentsFunctions.currencies()
                    case InstrumentType.INSTRUMENT_TYPE_FUTURES:
                        _INSTRUMENTS_CACHE[instrument_type] = await getInstrumentsFunctions.futures()
                    case InstrumentType.INSTRUMENT_TYPE_OPTION:
                        _INSTRUMENTS_CACHE[instrument_type] = await getInstrumentsFunctions.options()
        # Ищем инструмент по тикеру
        import json
        for item in _INSTRUMENTS_CACHE[instrument_type].instruments:
            if item.ticker == ticker:
                return item.figi
        raise ValueError(f"Инструмент с тикером '{ticker}' не найден")

def _extract_wait_time_from_error(error) -> int:
    """
    Извлекает время ожидания из сообщения об ошибке ограничения запросов.
    
    Args:
        error: Объект ошибки
        
    Returns:
        int: Время ожидания в секундах
    """
    match = re.search(r'ratelimit_reset=(\d+)', str(error))
    return int(match.group(1))


async def download_candles(ticker: str, from_date: datetime, to_date: datetime, interval: CandleInterval,
                           instrument_type: InstrumentType, max_retries: int = 5) -> pd.DataFrame:
    """
    Загружает исторические данные свечей с Tinkoff API.
    
    Args:
        ticker (str): Тикер инструмента
        from_date (datetime): Начальная дата периода
        to_date (datetime): Конечная дата периода
        interval (CandleInterval): Интервал свечей
        instrument_type (InstrumentType): Тип инструмента
        max_retries (int): Максимальное количество попыток при ошибках
        
    Returns:
        pd.DataFrame: DataFrame с данными свечей, индексированный по дате
    """
    retries = 0
    # Оцениваем общее количество свечей для прогресс-бара
    total_candles = (to_date - from_date) / candle_interval_to_timedelta(interval)
    # Повторяем попытки при ошибках
    while retries < max_retries:
        try:
            figi = await _get_figi_by_ticker(ticker, instrument_type)
            candles_data = []

            async with AsyncClient(TINKOFF_TOKEN) as client:
                async for candle in client.get_all_candles(
                    instrument_id=figi,
                    from_=from_date,
                    to=to_date,
                    interval=interval,
                    candle_source_type=CandleSource.CANDLE_SOURCE_EXCHANGE,
                ):
                    # Конвертируем данные свечи в удобный формат
                    candles_data.append({
                        'datetime': candle.time,
                        'open': float(quotation_to_decimal(candle.open)),
                        'high': float(quotation_to_decimal(candle.high)),
                        'low': float(quotation_to_decimal(candle.low)),
                        'close': float(quotation_to_decimal(candle.close)),
                        'volume': candle.volume
                    })
                    
                # СТЕР ПРОГРЕСС-БАР ПОСКОЛЬКУ МНЕ НЕ ПОНРАВИЛОСЬ, ЧТО total_candles подсчитывается неправильно, а T-invest API не предоставляет апишку которая считает общее количество свечей
                # with tqdm(total=total_candles, desc=f"Загрузка данных {ticker}", unit=" свечей") as pbar:
                #     async for candle in client.get_all_candles(
                #         instrument_id=figi,
                #         from_=from_date,
                #         to=to_date,
                #         interval=interval,
                #         candle_source_type=CandleSource.CANDLE_SOURCE_EXCHANGE,
                #     ):
                #         # Конвертируем данные свечи в удобный формат
                #         candles_data.append({
                #             'datetime': candle.time,
                #             'open': float(quotation_to_decimal(candle.open)),
                #             'high': float(quotation_to_decimal(candle.high)),
                #             'low': float(quotation_to_decimal(candle.low)),
                #             'close': float(quotation_to_decimal(candle.close)),
                #             'volume': candle.volume
                #         })
                #         pbar.update(1)  # Обновляем на каждой свече


            # Создаем DataFrame и настраиваем индекс
            df = pd.DataFrame(candles_data)
            if not df.empty:
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
            return df

        except Exception as e:
            retries += 1
            # Обрабатываем ограничение запросов
            if 'RESOURCE_EXHAUSTED' in str(e) or 'ratelimit' in str(e).lower():
                wait_time = _extract_wait_time_from_error(e)
                logger.error(f"{ticker}: RESOURCE_EXHAUSTED. Попытка {retries}/{max_retries}. Ждем {wait_time} сек...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"{ticker}: Ошибка {e}. Попытка {retries}/{max_retries}")
                await asyncio.sleep(10)
    return pd.DataFrame()

async def load_candles_local(ticker: str, interval: CandleInterval, instrument_type: InstrumentType,
                       from_date: datetime, to_date: datetime) -> Optional[pd.DataFrame]:
    """
    Загружает данные свечей только из локального файла без обращения к API.
    
    Args:
        ticker (str): Тикер инструмента
        interval (CandleInterval): Интервал свечей
        instrument_type (InstrumentType): Тип инструмента (не используется, но оставлен для совместимости)
        from_date (datetime): Начальная дата периода
        to_date (datetime): Конечная дата периода
        
    Returns:
        Optional[pd.DataFrame]: DataFrame с данными или None, если файл не найден
    """
    # Ищем существующий файл с данными
    existing_file = _find_existing_file(ticker, interval)
    if existing_file:
        df_existing = pd.read_csv(existing_file)
        df_existing['datetime'] = pd.to_datetime(df_existing['datetime'])
        df_existing.set_index('datetime', inplace=True)  
        return df_existing
    return None

async def load_candles(ticker: str, interval: CandleInterval, instrument_type: InstrumentType,
                       from_date: datetime, to_date: datetime) -> Optional[pd.DataFrame]:
    """
    Основная функция для загрузки данных свечей.
    
    Комбинирует локальные данные с загрузкой недостающих данных через API.
    Автоматически обновляет локальные файлы при необходимости.
    
    Args:
        ticker (str): Тикер инструмента
        interval (CandleInterval): Интервал свечей
        instrument_type (InstrumentType): Тип инструмента
        from_date (datetime): Начальная дата периода
        to_date (datetime): Конечная дата периода
        
    Returns:
        Optional[pd.DataFrame]: DataFrame с данными свечей или None при ошибке
    """
    directories: initial_setup.DirectoriesForReports =  initial_setup.createDirectoriesFromEnvVar()
    # Ищем существующий файл с данными
    existing_file = _find_existing_file(ticker, interval, directories.uncheckedReportsDirectory)

    if existing_file:
        logger.debug('Файл существует. Проверяем условие на необходимость подгрузить доп.данные')
        all_data_parts = []

        # Загружаем существующие данные
        df_existing = pd.read_csv(existing_file)
        df_existing['datetime'] = pd.to_datetime(df_existing['datetime'])
        df_existing.set_index('datetime', inplace=True)
        old_start_date, old_end_date = _parse_dates_from_filename(existing_file, interval)
        # Проверяем, нужны ли дополнительные данные слева или справа
        need_left = from_date < old_start_date
        need_right = to_date > old_end_date
        
        # Если все данные уже есть в файле, просто фильтруем
        if not need_left and not need_right:
            result_df = df_existing[(df_existing.index >= from_date) & (df_existing.index <= to_date)]
            result_df.index.name = 'datetime'
            return result_df

        all_data_parts.append(df_existing)

        # Загружаем недостающие данные слева
        if need_left:
            logger.debug('Необходимо загрузить недостающие данные слева')
            df_left = await download_candles(ticker, from_date, old_start_date, interval, instrument_type)
            if not df_left.empty:
                all_data_parts.insert(0, df_left)

        # Загружаем недостающие данные справа
        if need_right:
            logger.debug('Необходимо загрузить недостающие данные справа')
            df_right = await download_candles(ticker, old_end_date, to_date, interval, instrument_type)
            if not df_right.empty:
                all_data_parts.append(df_right)

        # Объединяем все части данных
        df_combined = pd.concat(all_data_parts)
        # Удаляем дубликаты по индексу (дата/время)
        df_combined = df_combined[~df_combined.index.duplicated(keep='first')]
        df_combined = df_combined.sort_index()
        
        # Сохраняем обновленный файл
        new_start, new_end = df_combined.index.min(), df_combined.index.max()
        os.remove(existing_file)
        df_combined.to_csv(directories.uncheckedReportsDirectory /  _generate_filename(ticker, interval, new_start, new_end), index=True)
        
        # Возвращаем запрошенный диапазон
        result_df = df_combined[(df_combined.index >= from_date) & (df_combined.index <= to_date)]
        result_df.index.name = 'datetime'
        return result_df
    else:
        logger.debug('Файл не существует. Полностью загружаем новые данные из T-API')
        # Если файл не существует, загружаем полностью новые данные
        df_new = await download_candles(ticker, from_date, to_date, interval, instrument_type)
        if not df_new.empty:
            start, end = df_new.index.min(), df_new.index.max()
            df_new.to_csv(directories.uncheckedReportsDirectory /  _generate_filename(ticker, interval, start, end), index=True)
            df_new.index.name = 'datetime'
            return df_new
        return None

async def load_multiple_candles(instruments: List[Dict], max_concurrent: int = 6) -> Dict[str, pd.DataFrame]:
    """
    Загружает данные для нескольких инструментов параллельно.
    
    Args:
        instruments (List[Dict]): Список словарей с параметрами для каждого инструмента.
                                 Каждый словарь должен содержать ключи: 
                                 ticker, interval, instrument_type, from_date, to_date
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
                logger.error(f"Ошибка {instrument['ticker']}: {e}")
                return instrument['ticker'], None

    # Запускаем параллельную обработку всех инструментов
    results = await asyncio.gather(*(process(inst) for inst in instruments))
    # Фильтруем успешные результаты
    return {ticker: df for ticker, df in results if df is not None and not df.empty}
