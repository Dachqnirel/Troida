# packages/data/checkAnomalies/find_anomalies.py
from abc import ABC
from typing import Tuple, Dict, Literal
import pandas as pd
import numpy as np
from pandas import DataFrame
from packages.core import logging


class AnomalyReport(dict):
    def __len__(self) -> int:
        idxs = []
        for v in self.values():
            if isinstance(v, (pd.DataFrame, pd.Series)):
                idxs.append(v.index)
        if not idxs:
            return 0
        unique_idx = pd.Index([])
        for idx in idxs:
            unique_idx = unique_idx.union(idx)
        return len(unique_idx)


class CheckAnomalyCandle(ABC):
    """
    Класс для обнаружения и устранения аномалий в OHLCV данных.
    """

    # ======================================================================
    # ОСНОВНОЙ МЕТОД
    # ======================================================================
    @staticmethod
    def checkAnomalyInCandles(
        df: DataFrame,
        mode: Literal["remove", "fix"] = "fix",
        vol_z_thresh: float = 3.5,
        price_mult: float = 6.0,
        rolling_window: int = 50,  # Установим значение по умолчанию
        tr_multiplier: float = 6.0, # Добавим отдельный множитель для True Range
        ret_multiplier: float = 6.0 # Добавим отдельный множитель для доходности
    ) -> Tuple[DataFrame, Dict[str, DataFrame]]:
        """Основной метод: аннотирует, затем удаляет или исправляет аномалии."""
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            logging.logger.warning("Передан пустой или некорректный DataFrame.")
            return pd.DataFrame(), AnomalyReport()

        annotated_df = CheckAnomalyCandle._annotate_anomalies(
            df.copy(), vol_z_thresh, price_mult, rolling_window, tr_multiplier, ret_multiplier
        )
        any_mask = annotated_df["is_anomaly"].astype(bool)

        # --- выбор режима ---
        if mode == "remove":
            clean_df = annotated_df.loc[~any_mask].drop(columns=["is_anomaly", "reasons"], errors="ignore")
            logging.logger.info("Режим: удаление аномалий.")
        elif mode == "fix":
            clean_df = CheckAnomalyCandle._fix_anomalies(
                annotated_df.copy(), vol_z_thresh, price_mult, rolling_window, tr_multiplier, ret_multiplier
            )
            logging.logger.info("Режим: исправление аномалий.")
        else:
            raise ValueError(f"Некорректный режим: {mode}")

        # --- формируем отчёт ---
        report = AnomalyReport()
        reasons_col = annotated_df["reasons"].fillna("")
        for reason in [
            "invalid_ohlc",
            "zero_volume_price_change",
            "volume_outliers",
            "price_outliers", # Этот тег будет включать все, что не попало в другие
        ]:
            mask = annotated_df["is_anomaly"] & reasons_col.apply(
                lambda s: reason in [r.strip() for r in s.split(";")] if s and pd.notna(s) else False
            )
            report[reason] = annotated_df.loc[mask, annotated_df.columns.drop(['is_anomaly', 'reasons'], errors='ignore')].copy()

        return clean_df.reset_index(drop=True), report

    # ======================================================================
    # РОБАСТНЫЙ Z-СКОР (вспомогательная функция)
    # ======================================================================
    @staticmethod
    def _robust_z(series: pd.Series, eps_mad: float = 1e-9) -> pd.Series:
        s = series.dropna()
        med = s.median() if not s.empty else 0.0
        mad = np.median(np.abs(s - med)) if not s.empty else 0.0
        if mad == 0 or np.isnan(mad):
            mad = eps_mad
        return 0.6745 * (series - med) / mad

    # ======================================================================
    # АННОТАЦИЯ АНОМАЛИЙ
    # ======================================================================
    @staticmethod
    def _annotate_anomalies(
        df: DataFrame, vol_z_thresh: float, price_mult: float, rolling_window: int, tr_multiplier: float, ret_multiplier: float
    ) -> DataFrame:
        df = df.copy()
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df.columns):
            annotated = df.copy()
            annotated["is_anomaly"] = True
            annotated["reasons"] = "invalid_ohlc"
            logging.logger.warning("Входной DataFrame не содержит всех колонок OHLCV.")
            return annotated

        eps = 1e-8
        # 1) базовая валидация OHLCV
        invalid_mask = (
            (df[["open","high","low","close"]].le(0)).any(axis=1) |
            (df['high'] < df['low']) |
            (df['high'] < df[['open','close']].max(axis=1)) |
            (df['low']  > df[['open','close']].min(axis=1)) |
            (df['volume'].fillna(-1) < 0) |
            (df[['open','high','low','close','volume']].isna().any(axis=1))
        )

        # 2) zero volume with price move (с допусками по float)
        price_moved_mask = (df['high'] - df['low']).abs() > eps
        zero_vol_move_mask = (df['volume'].fillna(0) == 0) & price_moved_mask

        # 3) volume outliers (robust, верхняя граница)
        x_log_vol = np.log1p(df['volume'].astype(float).clip(lower=0))
        med_vol = np.median(x_log_vol)
        mad_vol = 1.4826*np.median(np.abs(x_log_vol-med_vol)) or 1.0
        vol_hi_mask = (x_log_vol - med_vol)/mad_vol > vol_z_thresh

        # 4) price outliers (волатильностной)
        prev_close_series = df['close'].shift(1)
        # Используем np.maximum.reduce, но результат сохраняем как pd.Series с индексом df
        tr_values_arr = np.maximum.reduce([
            df['high'] - df['low'],
            (df['high'] - prev_close_series).abs(),
            (df['low']  - prev_close_series).abs()
        ])
        tr_series = pd.Series(tr_values_arr, index=df.index)

        # Используем rolling_window для робастной ATR
        # Исправлено: min_periods не может быть больше window
        ratr_window_size = rolling_window if rolling_window > 1 else 10
        ratr_min_periods_val = min(ratr_window_size, 10) # min_periods <= window
        ratr_series = tr_series.rolling(ratr_window_size, min_periods=ratr_min_periods_val).median().fillna(method="bfill").fillna(method="ffill")
        mask_tr_bool = tr_series > tr_multiplier * ratr_series # Используем отдельный множитель

        r_log_ret = np.log(df['close'] / prev_close_series).abs()
        # Для робастной сигмы доходности также используем rolling, если window задан
        # Это сложнее, т.к. нужно считать MAD доходностей в окне
        # Пока оставим глобальную, как в описании
        r_cleaned_ser = r_log_ret.dropna()
        if len(r_cleaned_ser) > 0:
            sigma_ret = 1.4826 * np.median(np.abs(r_cleaned_ser - np.median(r_cleaned_ser)))
            mask_ret_bool = r_log_ret > ret_multiplier * sigma_ret # Используем отдельный множитель
        else:
            # Если не хватает данных для расчёта sigma, не считаем аномалии по доходности
            mask_ret_bool = pd.Series([False] * len(df), index=df.index)

        masks_dict = {
            'invalid_ohlc': invalid_mask,
            'zero_volume_price_change': zero_vol_move_mask,
            'volume_outliers': vol_hi_mask,
            'price_outliers': (mask_tr_bool | mask_ret_bool)
        }

        # собрать причины
        reasons_list = []
        for name, m in masks_dict.items():
            m_series = pd.Series(m, index=df.index)
            # Исправлено: проверка на пустоту массива reasons_list
            if len(reasons_list) == 0: # Вместо `if not reasons_list:`
                reasons_list = np.where(m_series, name, '')
            else:
                reasons_series = pd.Series(reasons_list, index=df.index)
                combined_reasons = np.where(m_series & (reasons_series != ''),
                                   reasons_series + ';' + name,
                                   np.where(m_series, name, reasons_series))
                reasons_list = combined_reasons
        reasons_series_final = pd.Series(reasons_list, index=df.index).replace('', np.nan)

        any_mask = np.zeros(len(df), dtype=bool)
        for m in masks_dict.values(): any_mask |= m

        df['is_anomaly'] = any_mask
        df['reasons'] = reasons_series_final

        counts = {k: int(v.sum()) for k, v in masks_dict.items()}
        logging.logger.info(f"Аномалии по типам: {counts}")

        return df

    # ======================================================================
    # ИСПРАВЛЕНИЕ АНОМАЛИЙ (до идеала)
    # ======================================================================
    @staticmethod
    def _fix_anomalies(
        df_orig: DataFrame, vol_z_thresh: float, price_mult: float, rolling_window: int, tr_multiplier: float, ret_multiplier: float
    ) -> DataFrame:
        fixed_df = df_orig.copy()
        eps = 1e-8 # Для сравнений

        # --- 1. Исправление базовых OHLCV ошибок ---
        # Исправляем high < low
        bad_ohlc_mask = fixed_df["high"] < fixed_df["low"]
        if bad_ohlc_mask.any():
            fixed_df.loc[bad_ohlc_mask, ["high", "low"]] = fixed_df.loc[bad_ohlc_mask, ["low", "high"]].values
            logging.logger.info(f"Исправлено {int(bad_ohlc_mask.sum())} баров с high < low")

        # --- 2. Исправление Zero Volume Price Change ---
        zero_move_mask = (fixed_df["volume"].fillna(0) == 0) & ((fixed_df["high"] - fixed_df["low"]).abs() > eps)
        if zero_move_mask.any():
            # Заменяем на медиану, но с учётом rolling или глобально
            if rolling_window and rolling_window > 1:
                # Используем rolling медиану объёма
                median_vol_rolling = fixed_df["volume"].rolling(rolling_window, min_periods=1).median()
                # Если rolling медиана для строки с zero_move = 0 или NaN, используем глобальную медиану ненулевых
                global_non_zero_med = fixed_df["volume"][fixed_df["volume"] > 0].median() if (fixed_df["volume"] > 0).any() else 1.0
                # Создаём серию, где 0 или NaN из rolling заменяются на global_non_zero_med
                median_vol_to_use = median_vol_rolling.where(
                    (median_vol_rolling != 0) & (median_vol_rolling.notna()), global_non_zero_med
                )
                fixed_df.loc[zero_move_mask, "volume"] = median_vol_to_use.loc[zero_move_mask]
            else:
                # Используем глобальную медиану ненулевых, если есть, иначе 1.0
                if (fixed_df["volume"] > 0).any():
                    median_vol = fixed_df["volume"][fixed_df["volume"] > 0].median()
                else:
                    median_vol = 1.0
                fixed_df.loc[zero_move_mask, "volume"] = median_vol # <-- Присваиваем скалярное значение
            logging.logger.info(f"Исправлено {int(zero_move_mask.sum())} баров с нулевым объёмом и ценовым движением.")

        # --- 3. Исправление Volume Outliers ---
        # Рассчитываем робастный Z-скор для лог-объёма
        vol_log = np.log1p(pd.to_numeric(fixed_df["volume"], errors="coerce").fillna(0).clip(lower=0))
        x_vol = vol_log
        # Используем rolling MAD если window задан, иначе глобальную
        if rolling_window and rolling_window > 1:
            # Рассчитываем rolling median
            med_rolling = x_vol.rolling(rolling_window, min_periods=1).median()
            # Рассчитываем rolling MAD
            mad_rolling = (x_vol - med_rolling).abs().rolling(rolling_window, min_periods=1).median()
            # Учет 1.4826 для MAD
            mad_rolling = 1.4826 * mad_rolling
            # Предотвращение деления на 0
            mad_rolling = mad_rolling.where(mad_rolling != 0, 1.0)
            z_rolling = (x_vol - med_rolling) / mad_rolling
            # Маска для верхних выбросов
            hi_mask = z_rolling > vol_z_thresh
            # Рассчитываем предельное значение на основе rolling значений
            limit_series = np.expm1(med_rolling + vol_z_thresh * mad_rolling / 1.4826)
            fixed_df.loc[hi_mask, "volume"] = limit_series.loc[hi_mask]
        else:
            # Используем глобальные значения (как в старой реализации)
            med = np.median(x_vol)
            mad = 1.4826 * np.median(np.abs(x_vol - med)) or 1.0
            z = (x_vol - med) / mad
            hi_mask = z > vol_z_thresh
            limit = float(np.expm1(med + vol_z_thresh * mad / 1.4826))
            fixed_df.loc[hi_mask, "volume"] = limit
            logging.logger.info(f"Исправлено {int(hi_mask.sum())} пиков объёма до {limit:.2f}")
        
        if hi_mask.any():
             logging.logger.info(f"Исправлено {int(hi_mask.sum())} пиков объёма с использованием робастного Z-score.")


        # --- 4. Исправление Price Outliers ---
        # Используем предыдущий close для TR и доходности
        prev_close_series = fixed_df['close'].shift(1)

        # Рассчитываем True Range как pd.Series
        tr_values = np.maximum.reduce([
            fixed_df['high'] - fixed_df['low'],
            (fixed_df['high'] - prev_close_series).abs(),
            (fixed_df['low']  - prev_close_series).abs()
        ])
        tr_series = pd.Series(tr_values, index=fixed_df.index)

        # Рассчитываем робастную ATR (rolling median TR)
        ratr_window_size = rolling_window if rolling_window > 1 else 10
        ratr_min_periods_val = min(ratr_window_size, 10)
        ratr_series = tr_series.rolling(ratr_window_size, min_periods=ratr_min_periods_val).median().fillna(method="bfill").fillna(method="ffill")

        # Маска для аномального TR
        tr_outlier_mask = tr_series > tr_multiplier * ratr_series

        # Рассчитываем лог-доходность
        r_log_ret = np.log(fixed_df['close'] / prev_close_series).abs()

        # Рассчитываем робастную сигму доходности (глобально, как в описании)
        # Это требует предварительного расчёта на всём столбце
        r_cleaned_ser = r_log_ret.dropna()
        if len(r_cleaned_ser) > 0:
            sigma_r = 1.4826 * np.median(np.abs(r_cleaned_ser - np.median(r_cleaned_ser)))
            # Маска для аномальной доходности
            ret_outlier_mask = r_log_ret > ret_multiplier * sigma_r
        else:
            ret_outlier_mask = pd.Series([False] * len(fixed_df), index=fixed_df.index)

        # Комбинированная маска для ценовых аномалий
        price_outlier_mask = tr_outlier_mask | ret_outlier_mask

        # --- Исправление значений, вызывающих аномалии ---
        # 4a. Исправление True Range (TR)
        if tr_outlier_mask.any():
            tr_limit = tr_multiplier * ratr_series
            tr_current = tr_series.loc[tr_outlier_mask]
            excess_factor = tr_current / tr_limit.loc[tr_outlier_mask]

            # Пример стратегии: уменьшить high и/или увеличить low пропорционально
            # Определяем, что конкретно вызывает TR (high-prev_close, low-prev_close, high-low)
            # Для упрощения, уменьшаем размах (high - low), сохранив при этом close (или open) как можно ближе
            # Возьмём среднюю точку (open + close) / 2 как ориентир и скорректируем high и low относительно неё
            
            # Используем close как фиксированную точку и скорректируем high и low
            mid_point = fixed_df.loc[tr_outlier_mask, ['open', 'close']].mean(axis=1)
            
            # Новый допустимый диапазон
            new_half_range = (tr_limit.loc[tr_outlier_mask]) / 2
            
            # Новые значения high и low
            new_high = mid_point + new_half_range.loc[tr_outlier_mask]
            new_low = mid_point - new_half_range.loc[tr_outlier_mask]

            # Обновляем значения, если они нарушают базовые правила (high >= close, low <= close)
            # и если это уменьшает TR
            fixed_df.loc[tr_outlier_mask, 'high'] = np.minimum(fixed_df.loc[tr_outlier_mask, 'high'], new_high)
            fixed_df.loc[tr_outlier_mask, 'low'] = np.maximum(fixed_df.loc[tr_outlier_mask, 'low'], new_low)
            
            # Пересчитываем TR *только для строк, которые были исправлены* для проверки
            # Используем индекс tr_outlier_mask для фильтрации
            prev_close_for_outliers = prev_close_series.loc[tr_outlier_mask]
            new_tr_values = np.maximum.reduce([
                fixed_df.loc[tr_outlier_mask, 'high'] - fixed_df.loc[tr_outlier_mask, 'low'],
                (fixed_df.loc[tr_outlier_mask, 'high'] - prev_close_for_outliers).abs(),
                (fixed_df.loc[tr_outlier_mask, 'low']  - prev_close_for_outliers).abs()
            ])
            # Теперь длина new_tr_values должна совпадать с длиной tr_outlier_mask
            new_tr = pd.Series(new_tr_values, index=tr_outlier_mask.index[tr_outlier_mask]) # <-- ИСПРАВЛЕНО
            # Убедимся, что TR теперь <= лимиту
            # В этой упрощённой версии мы просто устанавливаем high/low, исходя из лимита
            # Более сложная логика может потребоваться для точного соответствия TR
            
            logging.logger.info(f"Исправлено {int(tr_outlier_mask.sum())} баров с аномальным True Range.")

        # 4b. Исправление Close для аномальной доходности (r)
        if ret_outlier_mask.any():
            # Рассчитываем максимально допустимую доходность
            r_limit = ret_multiplier * sigma_r
            
            # Определяем направление доходности (up/down)
            is_positive_ret = (fixed_df.loc[ret_outlier_mask, 'close'] - prev_close_series.loc[ret_outlier_mask]) > 0
            
            # Рассчитываем максимально допустимый close
            new_close_up = prev_close_series.loc[ret_outlier_mask] * np.exp(r_limit)
            new_close_down = prev_close_series.loc[ret_outlier_mask] * np.exp(-r_limit)
            
            # Применяем исправление
            mask_up = ret_outlier_mask & is_positive_ret
            mask_down = ret_outlier_mask & (~is_positive_ret)
            
            if mask_up.any():
                fixed_df.loc[mask_up, 'close'] = np.minimum(fixed_df.loc[mask_up, 'close'], new_close_up.loc[mask_up])
                # Также может потребоваться корректировка high
                fixed_df.loc[mask_up, 'high'] = np.maximum(fixed_df.loc[mask_up, 'high'], fixed_df.loc[mask_up, 'close'])
            
            if mask_down.any():
                fixed_df.loc[mask_down, 'close'] = np.maximum(fixed_df.loc[mask_down, 'close'], new_close_down.loc[mask_down])
                # Также может потребоваться корректировка low
                fixed_df.loc[mask_down, 'low'] = np.minimum(fixed_df.loc[mask_down, 'low'], fixed_df.loc[mask_down, 'close'])
            
            logging.logger.info(f"Исправлено {int(ret_outlier_mask.sum())} баров с аномальной доходностью.")

        # --- 5. Финальная проверка и очистка ---
        # Удаляем служебные колонки
        fixed_df = fixed_df.drop(columns=["is_anomaly", "reasons"], errors="ignore")
        
        # Удаляем дубликаты datetime, если есть
        if "datetime" in fixed_df.columns and fixed_df["datetime"].duplicated().any():
            dupes = int(fixed_df["datetime"].duplicated().sum())
            fixed_df = fixed_df.drop_duplicates(subset="datetime", keep="first")
            logging.logger.warning(f"Удалено {dupes} дубликатов datetime.")

        # Финальная интерполяция для ликвидации возможных оставшихся пропусков или небольших нарушений
        # Исправлено: используем method="linear", так как index не DatetimeIndex
        for col in ["open", "high", "low", "close", "volume"]:
            if col in fixed_df.columns:
                fixed_df[col] = pd.to_numeric(fixed_df[col], errors="coerce")
                # Используем метод, который НЕ зависит от DatetimeIndex
                fixed_df[col] = fixed_df[col].interpolate(method="linear", limit_direction="both")
        
        return fixed_df.reset_index(drop=True)