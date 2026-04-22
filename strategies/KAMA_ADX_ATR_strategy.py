#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import backtrader as bt
import pandas as pd
import requests
from datetime import datetime, timedelta
import sys

# ============================================================================
# ПОЛУЧЕНИЕ ДАННЫХ С MOEX
# ============================================================================

def get_moex_data(ticker='SBER', days_back=365, interval='1D'):
    """
    Получение исторических данных с МосБиржи через ISS JSON с перебором досок и пагинацией.
    """
    try:
        print(f'\n Загрузка данных {ticker} с МосБиржи...')

        end_date = datetime.now().date()
        start_date = (datetime.now() - timedelta(days=days_back)).date()

        boards = ['TQBR', 'TQTF', 'TQTD']  # Основная и запасные доски
        interval_map = {'1m': 1, '10m': 10, '60m': 60, '1D': 24}
        iss_interval = interval_map.get(interval, 60)
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) BacktraderBot/1.0'
        })

        all_rows = []
        used_board = None

        for board in boards:
            base = (
                f'https://iss.moex.com/iss/engines/stock/markets/shares/boards/{board}/'
                f'securities/{ticker}/candles.json'
            )
            start_param = 0
            rows = []

            while True:
                params = {
                    'from': str(start_date),
                    'till': str(end_date),
                    'interval': str(iss_interval),
                    'start': str(start_param)
                }
                resp = session.get(base, params=params, timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
                candles = data.get('candles', {})
                columns = candles.get('columns', [])
                data_rows = candles.get('data', [])

                if not data_rows:
                    break

                rows.extend(data_rows)

                # Пагинация: если вернулось меньше стандартного чанка (100), завершаем
                if len(data_rows) < 100:
                    break
                start_param += len(data_rows)

            if rows:
                all_rows = rows
                used_board = board
                break

        if not all_rows:
            print(f'Ошибка: Не удалось загрузить данные для {ticker}')
            print('Проверьте тикер (например: SBER, GAZP, LKOH, ROSN) и доступные доски: TQBR/TQTF/TQTD')
            return None

        # Сборка DataFrame из JSON
        df_raw = pd.DataFrame(all_rows, columns=columns)
        required_cols = {'begin', 'open', 'high', 'low', 'close'}
        if not required_cols.issubset(set(df_raw.columns)):
            print('Неожиданная структура ответа ISS (нет необходимых столбцов)')
            return None

        volume_col = 'volume' if 'volume' in df_raw.columns else ('value' if 'value' in df_raw.columns else None)
        if volume_col is None:
            df_raw['volume'] = 0
            volume_col = 'volume'

        df = pd.DataFrame({
            'datetime': pd.to_datetime(df_raw['begin']),
            'open': df_raw['open'].astype(float),
            'high': df_raw['high'].astype(float),
            'low': df_raw['low'].astype(float),
            'close': df_raw['close'].astype(float),
            'volume': df_raw[volume_col].astype(float)
        })

        df.set_index('datetime', inplace=True)
        df = df.sort_index()
        # Чистка данных: уберём дубликаты/NaN/некорректные бары
        df = df[~df.index.duplicated(keep='last')]
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        # Убедимся, что high/low/close/open положительные
        df = df[(df['open'] > 0) & (df['high'] > 0) & (df['low'] > 0) & (df['close'] > 0)]
        # Исправим нулевой диапазон свечи (high==low), чтобы избежать деления на ноль в DI/ADX
        zero_range = df['high'] == df['low']
        if zero_range.any():
            eps = 1e-6
            df.loc[zero_range, 'high'] = df.loc[zero_range, 'close'] * (1.0 + eps)
            df.loc[zero_range, 'low'] = df.loc[zero_range, 'close'] * (1.0 - eps)
        # Удалим полностью «плоские» бары без объёма
        flat_no_vol = (df['open'] == df['close']) & (df['high'] == df['low']) & (df['volume'] == 0)
        df = df[~flat_no_vol]
        # Volume может быть нулевым на некоторых барах — заменим NaN/negatives нулями
        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).clip(lower=0)

        print(f'Загружено {len(df)} баров (доска: {used_board}, интервал: {interval})')
        print(f'Период: {df.index[0].strftime("%d.%m.%Y")} - {df.index[-1].strftime("%d.%m.%Y")}')

        return df

    except Exception as e:
        print(f'\n Ошибка при загрузке данных: {e}')
        return None


# ============================================================================
# ПОЛУЧЕНИЕ ДАННЫХ С КРИПТОБИРЖ (через ccxt)
# ============================================================================

def get_crypto_data(symbol='BTC/USDT', days_back=365, interval='1D', exchange_name='kucoin'):
    """
    Загрузка исторических данных с криптобиржи (ccxt). По умолчанию KuCoin.
    symbol: формат 'BTC/USDT'
    interval: '1m'|'10m'|'60m'|'1D' -> маппинг в ccxt: '1m','10m','1h','1d'
    """
    try:
        import ccxt
    except ImportError:
        print('\n Библиотека ccxt не установлена! Установите: pip install ccxt')
        return None

    tf_map = {'1m': '1m', '10m': '10m', '60m': '1h', '1D': '1d'}
    timeframe = tf_map.get(interval, '1d')

    since_dt = datetime.utcnow() - timedelta(days=days_back)
    since_ms = int(since_dt.timestamp() * 1000)

    try:
        ex_cls = getattr(ccxt, exchange_name)
        ex = ex_cls()
        all_rows = []
        limit = 1000
        next_since = since_ms

        while True:
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=next_since, limit=limit)
            if not ohlcv:
                break
            all_rows.extend(ohlcv)
            if len(ohlcv) < limit:
                break
            next_since = ohlcv[-1][0] + 1

        if not all_rows:
            print(f'Нет данных для {symbol} на {exchange_name}')
            return None

        df = pd.DataFrame(all_rows, columns=['timestamp','open','high','low','close','volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df[['datetime','open','high','low','close','volume']]
        df.set_index('datetime', inplace=True)
        df = df.sort_index()
        df = df.dropna(subset=['open','high','low','close'])
        df = df[(df['open']>0)&(df['high']>0)&(df['low']>0)&(df['close']>0)]
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).clip(lower=0)

        print(f'Загружено {len(df)} баров {symbol} ({exchange_name}, {timeframe})')
        print(f'   Период: {df.index[0].strftime("%d.%m.%Y")} - {df.index[-1].strftime("%d.%m.%Y")})')
        return df
    except Exception as e:
        print(f'\n Ошибка загрузки крипто-данных: {e}')
        return None

# ============================================================================
# КАСТОМНЫЙ ИНДИКАТОР: CHANDE MOMENTUM OSCILLATOR (CMO)
# ============================================================================

class CMOIndicator(bt.Indicator):
    lines = ('cmo',)
    params = (('period', 14),)

    def __init__(self):
        price = self.data
        delta = price - price(-1)
        up = bt.If(delta > 0, delta, 0.0)
        down = bt.If(delta < 0, -delta, 0.0)

        sum_up = bt.indicators.SumN(up, period=self.p.period)
        sum_down = bt.indicators.SumN(down, period=self.p.period)

        denom = bt.If((sum_up + sum_down) != 0, (sum_up + sum_down), 1e-12)
        self.l.cmo = 100.0 * (sum_up - sum_down) / denom


# ============================================================================
# СТРАТЕГИЯ С 3 ИНДИКАТОРАМИ
# ============================================================================

class ImprovedKAMAStrategy(bt.Strategy):
    """
    Единая стратегия на основе KAMA с фильтрами ADX/DI, ATR и CMO,
    с динамическим размером позиции, трейлинг-стопом и защитой от просадки.
    """

    params = (
        # Параметры KAMA
        ('kama_period', 10),
        ('kama_fast', 2),
        ('kama_slow', 30),
        # ADX/DI
        ('adx_period', 14),
        ('adx_threshold', 15),
        # ATR и цели/стопы
        ('atr_period', 14),
        ('atr_stop_multiplier', 1.5),
        ('atr_target_multiplier', 4.0),
        # Риск-менеджмент
        ('risk_percent', 0.02),  # 2% от капитала (по умолчанию)
        ('verbose', True),
    )

    def __init__(self):
        # Минимальный разогрев, чтобы индикаторы имели достаточную историю
        self.addminperiod(max(50, self.params.kama_period + self.params.adx_period + self.params.atr_period))
        # Индикаторы тренда/волатильности
        self.kama = bt.indicators.KAMA(
            self.datas[0],
            period=self.params.kama_period,
            fast=self.params.kama_fast,
            slow=self.params.kama_slow,
        )

        self.adx = bt.indicators.AverageDirectionalMovementIndex(
            self.datas[0], period=self.params.adx_period
        )
        self.plus_di = bt.indicators.PlusDI(self.datas[0], period=self.params.adx_period)
        self.minus_di = bt.indicators.MinusDI(self.datas[0], period=self.params.adx_period)

        self.atr = bt.indicators.AverageTrueRange(self.datas[0], period=self.params.atr_period)
        self.atr_sma20 = bt.indicators.SMA(self.atr, period=20)

        # Осциллятор перекупленности/перепроданности
        self.cmo = CMOIndicator(self.datas[0], period=14)

        # Состояние сделки/капитала
        self.buy_price = None
        self.stop_loss = None
        self.take_profit = None
        self.order = None
        self.trade_count = 0
        self.win_count = 0
        self.lose_count = 0

        # Трейлинг и просадка
        self.trailing_active = False
        self.peak_value = None
        self.size_multiplier = 1.0

    def log(self, txt, dt=None):
        if self.params.verbose:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.strftime("%d.%m.%Y")} | {txt}')

    def _update_drawdown_state(self):
        equity = self.broker.getvalue()
        if self.peak_value is None or equity > self.peak_value:
            self.peak_value = equity

        if equity <= 0.9 * self.peak_value and self.size_multiplier > 0.6:
            self.size_multiplier = 0.5
            self.log(f'⚠️ Защита от просадки активирована | Equity: {equity:.2f} | Peak: {self.peak_value:.2f}')
        elif equity >= 0.95 * self.peak_value and self.size_multiplier < 1.0:
            self.size_multiplier = 1.0
            self.log(f'Восстановление после просадки | Equity: {equity:.2f} | Peak: {self.peak_value:.2f}')

    def calculate_position_size(self, price, atr):
        cash = self.broker.get_cash()
        atr_avg = self.atr_sma20[0] if len(self) > 20 else atr
        if atr <= 0 or price <= 0:
            return 0

        # Базовый размер по волатильности
        size = (cash * self.params.risk_percent) / (atr * 1.5)

        # Коррекция по волатильности
        if atr < atr_avg:
            size *= 1.5
        elif atr > atr_avg:
            size *= 0.7
        if atr < 0.7 * atr_avg:
            size *= 1.3

        # Ограничения: не более 95% капитала
        max_size = (cash * 0.95) / price

        # Учитываем защитный множитель просадки
        size *= self.size_multiplier

        return int(max(0, min(size, max_size)))

    def next(self):
        if self.order:
            return

        current_price = self.data.close[0]
        current_atr = self.atr[0]
        atr_avg = self.atr_sma20[0] if len(self) > 20 else current_atr
        current_adx = self.adx[0]

        # Обновление состояния просадки
        self._update_drawdown_state()

        # Волатильный фильтр: слишком высокая волатильность — пропускаем вход
        if not self.position and current_atr > 2.0 * atr_avg:
            self.log(f'Вход отклонён: высокая волатильность ATR {current_atr:.2f} > 2.0×ATR_avg {atr_avg:.2f}')
            return

        # ===================== ВХОД =====================
        if not self.position:
            # Вход по KAMA: пересечение цены снизу вверх
            kama_cross_up = (self.data.close[-1] <= self.kama[-1] and current_price > self.kama[0])
            # Фильтры: тренд и волатильность, избегаем перекупленности
            not_overbought = self.cmo[0] < 40
            p_enter = (
                kama_cross_up and
                current_adx > self.params.adx_threshold and
                self.plus_di[0] > self.minus_di[0] and
                current_atr < 1.5 * atr_avg and
                not_overbought
            )

            if p_enter:
                size = self.calculate_position_size(current_price, current_atr)
                if size > 0:
                    self.order = self.buy(size=size)
                    self.stop_loss = current_price - (self.params.atr_stop_multiplier * current_atr)
                    self.take_profit = current_price + (self.params.atr_target_multiplier * current_atr)
                    self.trailing_active = False

                    self.log(
                        f'ПОКУПКА [KAMA-cross] | Цена: {current_price:.2f} ₽ | '
                        f'ADX: {current_adx:.1f} | CMO: {self.cmo[0]:.1f} | ATR: {current_atr:.2f} (avg {atr_avg:.2f}) | '
                        f'Размер: {size:.0f}'
                    )
                    self.log(f'   SL: {self.stop_loss:.2f} ₽ (1.5×ATR) | TP: {self.take_profit:.2f} ₽ (4×ATR)')

        # ===================== ВЫХОДЫ =====================
        else:
            # Выход 1: Цена пересекает KAMA сверху вниз
            kama_cross_down = (self.data.close[-1] >= self.kama[-1] and current_price < self.kama[0])

            # Выход 2: Перекупленность по CMO
            cmo_overbought = self.cmo[0] > 50

            # Выход 3: Стопы
            hit_stop = current_price <= self.stop_loss if self.stop_loss is not None else False
            hit_target = current_price >= self.take_profit if self.take_profit is not None else False

            # Выход 4: Трейлинг — активировать когда прибыль > 2×ATR, тянуть до 1×ATR
            if self.buy_price is not None:
                unrealized = current_price - self.buy_price
                if unrealized > 2 * current_atr:
                    new_sl = current_price - 1.0 * current_atr
                    if self.stop_loss is None or new_sl > self.stop_loss:
                        self.stop_loss = new_sl
                        self.trailing_active = True
                        self.log(f'🔧 Трейлинг-стоп подтянут до {self.stop_loss:.2f} ₽ (1×ATR)')

            if kama_cross_down or cmo_overbought or hit_stop or hit_target:
                if kama_cross_down:
                    reason = 'Выход: KAMA-cross ↓'
                elif cmo_overbought:
                    reason = 'Выход: CMO>50'
                elif hit_stop:
                    reason = 'Выход: Stop-Loss'
                else:
                    reason = 'Выход: Take-Profit'

                self.log(f'ПРОДАЖА | Цена: {current_price:.2f} ₽ | Причина: {reason}')
                self.order = self.close()
    
    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.trade_count += 1
            
            elif order.issell():
                if self.buy_price:
                    profit = (order.executed.price - self.buy_price) * order.executed.size
                    profit_pct = ((order.executed.price - self.buy_price) / self.buy_price) * 100
                    
                    if profit > 0:
                        self.win_count += 1
                        self.log(f'Прибыль: {profit:.2f} ₽ ({profit_pct:+.2f}%)')
                    else:
                        self.lose_count += 1
                        self.log(f'Убыток: {profit:.2f} ₽ ({profit_pct:+.2f}%)')
                    
                    self.buy_price = None
        
        self.order = None
    
    def calculate_position_size(self, price, atr):
        """Расчет размера позиции на основе риск-менеджмента"""
        cash = self.broker.get_cash()
        risk_amount = cash * self.params.risk_percent
        stop_distance = self.params.atr_stop_multiplier * atr
        
        if stop_distance > 0:
            size = risk_amount / stop_distance
            max_size = cash / price * 0.95
            return min(int(size), int(max_size))
        return 0
    
    def stop(self):
        """Финальная статистика"""
        if self.params.verbose:
            print('\n' + '='*70)
            print('СТАТИСТИКА СДЕЛОК')
            print('='*70)
            print(f'Всего сделок: {self.trade_count}')
            if self.trade_count > 0:
                print(f'Прибыльных: {self.win_count} ({self.win_count/self.trade_count*100:.1f}%)')
                print(f'Убыточных: {self.lose_count} ({self.lose_count/self.trade_count*100:.1f}%)')


# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА
# ============================================================================

def run_backtest(ticker='SBER', initial_cash=100000, days_back=365, 
                adx_threshold=25, risk_percent=2.0, commission=0.0003, interval='1D'):
    """
    Запуск бэктеста с заданными параметрами
    """
    print('\n' + '='*70)
    print('ЗАПУСК ТОРГОВОЙ СТРАТЕГИИ KAMA + ADX + ATR + CMO')
    print('='*70)
    
    # Загружаем данные
    data_df = get_moex_data(ticker, days_back, interval=interval)
    if data_df is None:
        return
    
    # Создаем cerebro
    cerebro = bt.Cerebro()
    
    # Добавляем данные с корректным таймфреймом/compression
    tf_map = {
        '1m': (bt.TimeFrame.Minutes, 1),
        '10m': (bt.TimeFrame.Minutes, 10),
        '60m': (bt.TimeFrame.Minutes, 60),
        '1D': (bt.TimeFrame.Days, 1),
    }
    timeframe, compression = tf_map.get(interval, (bt.TimeFrame.Minutes, 60))
    data_feed = bt.feeds.PandasData(
        dataname=data_df,
        timeframe=timeframe,
        compression=compression,
    )
    cerebro.adddata(data_feed)
    
    # Добавляем стратегию
    cerebro.addstrategy(
        ImprovedKAMAStrategy,
        adx_threshold=adx_threshold,
        risk_percent=risk_percent/100.0,
        verbose=True
    )
    
    # Настройки брокера
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)
    
    start_value = cerebro.broker.getvalue()
    
    # Параметры
    print(f'\n ПАРАМЕТРЫ:')
    print(f'   Тикер: {ticker}')
    print(f'   Начальный капитал: {initial_cash:,.0f} ₽')
    print(f'   Комиссия: {commission*100:.2f}%')
    print(f'   Порог ADX: {adx_threshold}')
    print(f'   Риск на сделку: {risk_percent}%')
    print(f'   Период данных: {days_back} дней')
    print(f'   Таймфрейм: {interval}')
    
    print('\n' + '-'*70)
    print('ТОРГОВЫЕ СИГНАЛЫ:')
    print('-'*70)
    
    # Запускаем
    cerebro.run()
    
    final_value = cerebro.broker.getvalue()
    
    # Результаты
    print('\n' + '='*70)
    print('ИТОГОВЫЕ РЕЗУЛЬТАТЫ')
    print('='*70)
    
    profit = final_value - start_value
    profit_pct = (profit / start_value) * 100
    
    print(f'Начальный капитал: {start_value:,.2f} ₽')
    print(f'Конечный капитал:  {final_value:,.2f} ₽')
    print(f'\nПрибыль/Убыток: {profit:+,.2f} ₽ ({profit_pct:+.2f}%)')
    
    # Buy & Hold сравнение
    initial_price = data_df['close'].iloc[0]
    final_price = data_df['close'].iloc[-1]
    buy_hold_pct = ((final_price - initial_price) / initial_price) * 100
    
    print(f'\nСтратегия Buy & Hold: {buy_hold_pct:+.2f}%')
    
    if profit_pct > buy_hold_pct:
        print(f'Стратегия ПРЕВЗОШЛА Buy & Hold на {profit_pct - buy_hold_pct:.2f}%')
    else:
        print(f'Стратегия уступила Buy & Hold на {buy_hold_pct - profit_pct:.2f}%')
    
    print('='*70 + '\n')
    
    # Построение графика
    try:
        print('Построение графика...')
        cerebro.plot(style='candlestick', volume=False, 
                    barup='green', bardown='red')
    except:
        print('Не удалось построить график (требуется matplotlib)')


# ============================================================================
# ЗАПУСК ИЗ КОМАНДНОЙ СТРОКИ
# ============================================================================

if __name__ == '__main__':
    # Параметры по умолчанию для быстрого старта
    TICKER = 'SBER'          # Тикер акции (SBER)
    INITIAL_CASH = 100000    # Начальный капитал в рублях
    DAYS_BACK = 700          # Сколько дней истории загрузить
    ADX_THRESHOLD = 25       # Минимальное значение ADX для входа (снижено)
    RISK_PERCENT = 15.0       # Процент риска на сделку
    COMMISSION = 0.0003      # Комиссия брокера (0.03%)
    
    print("""
    ================================================================
                        ТОРГОВАЯ СТРАТЕГИЯ 
                 KAMA + ADX + ATR (Trend Following)
    ================================================================
    """)
    
    run_backtest(
        ticker=TICKER,
        initial_cash=INITIAL_CASH,
        days_back=DAYS_BACK,
        adx_threshold=ADX_THRESHOLD,
        risk_percent=RISK_PERCENT,
        commission=COMMISSION,
        interval='1D'
    )
