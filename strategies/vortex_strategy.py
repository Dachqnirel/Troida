import argparse
import numpy as np
import pandas as pd

from rolling_catboost import load_csv, sharpe_and_sum


def _preset_params(preset: str) -> dict:
    preset = (preset or "").strip().lower()
    if preset in ("trend", "long", "long_only"):
        # Параметры, которые дали >=15% на BTC/ETH (исходные датасеты)
        return dict(
            donchian_period=40,
            ema_period=250,
            rsi_long=60.0,
            allow_short=False,
        )
    if preset in ("bear", "bear_short"):
        # Параметры, которые вытащили BTC 2021-2022 (bear regime + shorts)
        return dict(
            donchian_period=55,
            ema_period=250,
            rsi_long=60.0,
            rsi_short=35.0,
            allow_short=True,
            short_mode="bear",
            ema_slope_period=20,
            ema_slope_threshold=0.0,
        )
    raise ValueError(f"Unknown preset: {preset}. Use: auto|trend|bear|custom")


def compute_regime(
    close: pd.Series,
    ema_period: int = 250,
    slope_period: int = 20,
    lookback: int = 200,
    threshold: float = 0.0,
) -> pd.Series:
    """
    Regime (trend/bear) БЕЗ заглядывания в будущее:
    - считаем EMA(ema_period)
    - считаем наклон EMA за slope_period
    - берём rolling mean наклона по lookback и сдвигаем на 1 бар, чтобы режим на баре t
      был известен до принятия решения на этом баре.
    """
    ema = compute_ema(close.astype(float), ema_period)
    ema_ref = ema.shift(slope_period)
    ema_slope = (ema - ema_ref) / (ema_ref.abs() + 1e-12)
    score = ema_slope.rolling(lookback, min_periods=1).mean().shift(1).fillna(0.0)
    regime = pd.Series(np.where(score >= threshold, "trend", "bear"), index=close.index)
    return regime


def compute_vortex(high, low, close, period=14):
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    vm_plus = (high - prev_low).abs()
    vm_minus = (low - prev_high).abs()

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    tr_sum = tr.rolling(period, min_periods=1).sum()
    vi_plus = vm_plus.rolling(period, min_periods=1).sum() / (tr_sum + 1e-12)
    vi_minus = vm_minus.rolling(period, min_periods=1).sum() / (tr_sum + 1e-12)

    return vi_plus, vi_minus


def compute_donchian(high, low, period=20):
    upper = high.rolling(period, min_periods=1).max()
    lower = low.rolling(period, min_periods=1).min()
    mid = (upper + lower) / 2.0
    return upper, lower, mid


def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()

    rs = avg_gain / (avg_loss + 1e-12)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def compute_ema(close, period=200):
    return close.ewm(span=period, adjust=False).mean()


def compute_atr(high, low, close, period=14):
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.rolling(period, min_periods=1).mean()


def calculate_cagr(returns: pd.Series, bars_per_year: int = 4380) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    if len(equity) < 2:
        return 0.0

    total_return = float(equity.iloc[-1])
    years = len(equity) / float(bars_per_year)
    if years <= 0:
        return 0.0

    return total_return ** (1.0 / years) - 1.0


def calculate_max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    peak = equity.cummax()
    dd = equity / (peak + 1e-12) - 1.0
    return float(dd.min())


def calculate_profit_factor(returns: pd.Series) -> float:
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    if losses <= 1e-12:
        return float("inf")
    return gains / losses


def strategy(
    close,
    high,
    low,
    vi_plus,
    vi_minus,
    upper,
    lower,
    mid,
    rsi,
    ema,
    atr,
    rsi_long=55.0,
    rsi_short=45.0,
    allow_short=True,
    short_mode="always",  # always|bear|never
    ema_slope_period=20,
    ema_slope_threshold=0.0,
    cost_bps=5.0,
):
    n = len(close)
    pos = np.zeros(n, dtype=int)
    trades = np.zeros(n, dtype=int)
    curr = 0

    r = close.pct_change().fillna(0.0).values
    cost = cost_bps / 10000.0
    atr_mean = atr.rolling(100, min_periods=1).mean()
    ema_ref = ema.shift(ema_slope_period)
    ema_slope = (ema - ema_ref) / (ema_ref.abs() + 1e-12)

    for t in range(1, n):
        new = curr

        atr_filter = atr.iloc[t] > atr_mean.iloc[t]
        bull_filter = ema_slope.iloc[t] >= ema_slope_threshold
        bear_filter = ema_slope.iloc[t] <= -ema_slope_threshold

        long_entry = (
            vi_plus.iloc[t] > vi_minus.iloc[t]
            and close.iloc[t] > ema.iloc[t]
            and close.iloc[t - 1] <= upper.iloc[t - 1]
            and close.iloc[t] > upper.iloc[t - 1]
            and rsi.iloc[t] >= rsi_long
            and atr_filter
            and bull_filter
        )

        long_exit = (
            vi_plus.iloc[t] < vi_minus.iloc[t]
            or close.iloc[t] < ema.iloc[t]
            or close.iloc[t] < mid.iloc[t]
        )

        short_allowed = allow_short and (short_mode != "never")
        if short_mode == "bear":
            short_allowed = short_allowed and bear_filter

        short_entry = (
            short_allowed
            and vi_minus.iloc[t] > vi_plus.iloc[t]
            and close.iloc[t] < ema.iloc[t]
            and close.iloc[t - 1] >= lower.iloc[t - 1]
            and close.iloc[t] < lower.iloc[t - 1]
            and rsi.iloc[t] <= rsi_short
            and atr_filter
        )

        short_exit = (
            vi_minus.iloc[t] < vi_plus.iloc[t]
            or close.iloc[t] > ema.iloc[t]
            or close.iloc[t] > mid.iloc[t]
        )

        if curr == 0:
            if long_entry:
                new = 1
            elif short_entry:
                new = -1
        elif curr == 1:
            if long_exit:
                new = 0
        elif curr == -1:
            if short_exit:
                new = 0

        if new != curr:
            trades[t] = 1
            curr = new

        pos[t] = curr

    strat = np.insert(pos[:-1] * r[1:], 0, 0.0)
    strat -= trades * cost * np.abs(np.diff(np.insert(pos, 0, 0)))

    return pd.Series(strat, index=close.index), pd.Series(pos, index=close.index)


def adaptive_strategy(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    vi_plus: pd.Series,
    vi_minus: pd.Series,
    upper_trend: pd.Series,
    lower_trend: pd.Series,
    mid_trend: pd.Series,
    upper_bear: pd.Series,
    lower_bear: pd.Series,
    mid_bear: pd.Series,
    rsi: pd.Series,
    ema: pd.Series,
    atr: pd.Series,
    regime: pd.Series,
    # trend params
    rsi_long_trend: float = 60.0,
    # bear params
    rsi_long_bear: float = 60.0,
    rsi_short_bear: float = 35.0,
    cost_bps: float = 5.0,
) -> tuple[pd.Series, pd.Series]:
    """
    Адаптивная стратегия без lookahead:
    - regime[t] определяется только прошлой историей (см. compute_regime)
    - при trend: long-only (жёсткий вход, как в трендовом пресете)
    - при bear: допускаем short (и long тоже можно, но входы фильтруются тем же режимом)
    """
    n = len(close)
    pos = np.zeros(n, dtype=int)
    trades = np.zeros(n, dtype=int)
    curr = 0

    r = close.pct_change().fillna(0.0).values
    cost = cost_bps / 10000.0
    atr_mean = atr.rolling(100, min_periods=1).mean()

    for t in range(1, n):
        new = curr
        atr_filter = atr.iloc[t] > atr_mean.iloc[t]
        is_trend = str(regime.iloc[t]) == "trend"

        if is_trend:
            up = upper_trend
            lo = lower_trend
            md = mid_trend
            rsi_long = rsi_long_trend
        else:
            up = upper_bear
            lo = lower_bear
            md = mid_bear
            rsi_long = rsi_long_bear

        long_entry = (
            vi_plus.iloc[t] > vi_minus.iloc[t]
            and close.iloc[t] > ema.iloc[t]
            and close.iloc[t - 1] <= up.iloc[t - 1]
            and close.iloc[t] > up.iloc[t - 1]
            and rsi.iloc[t] >= rsi_long
            and atr_filter
            and is_trend  # long только в trend-режиме
        )

        long_exit = (
            vi_plus.iloc[t] < vi_minus.iloc[t]
            or close.iloc[t] < ema.iloc[t]
            or close.iloc[t] < md.iloc[t]
        )

        short_entry = (
            (not is_trend)
            and vi_minus.iloc[t] > vi_plus.iloc[t]
            and close.iloc[t] < ema.iloc[t]
            and close.iloc[t - 1] >= lo.iloc[t - 1]
            and close.iloc[t] < lo.iloc[t - 1]
            and rsi.iloc[t] <= rsi_short_bear
            and atr_filter
        )

        short_exit = (
            vi_minus.iloc[t] < vi_plus.iloc[t]
            or close.iloc[t] > ema.iloc[t]
            or close.iloc[t] > md.iloc[t]
        )

        if curr == 0:
            if long_entry:
                new = 1
            elif short_entry:
                new = -1
        elif curr == 1:
            if long_exit:
                new = 0
        elif curr == -1:
            if short_exit:
                new = 0

        if new != curr:
            trades[t] = 1
            curr = new
        pos[t] = curr

    strat = np.insert(pos[:-1] * r[1:], 0, 0.0)
    strat -= trades * cost * np.abs(np.diff(np.insert(pos, 0, 0)))
    return pd.Series(strat, index=close.index), pd.Series(pos, index=close.index)


def main():
    print("Starting strategy script...")

    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--preset", type=str, default="custom", help="custom|trend|bear")
    ap.add_argument("--mode", type=str, default="static", help="static|adaptive")
    ap.add_argument("--regime_lookback", type=int, default=200)
    ap.add_argument("--regime_slope_period", type=int, default=20)
    ap.add_argument("--regime_threshold", type=float, default=0.0)
    ap.add_argument("--bars_per_year", type=int, default=4380)
    ap.add_argument("--donchian_period", type=int, default=20)
    ap.add_argument("--ema_period", type=int, default=200)
    ap.add_argument("--rsi_period", type=int, default=14)
    ap.add_argument("--rsi_long", type=float, default=55.0)
    ap.add_argument("--rsi_short", type=float, default=45.0)
    ap.add_argument("--allow_short", type=int, default=1)
    ap.add_argument("--short_mode", type=str, default="always", help="always|bear|never")
    ap.add_argument("--ema_slope_period", type=int, default=20)
    ap.add_argument("--ema_slope_threshold", type=float, default=0.0)
    ap.add_argument("--vortex_period", type=int, default=14)
    ap.add_argument("--atr_period", type=int, default=14)
    ap.add_argument("--cost_bps", type=float, default=5.0)
    args = ap.parse_args()

    print(f"Loading CSV: {args.csv}")
    df = load_csv(args.csv).copy()
    print(f"Loaded rows: {len(df)}")

    df.columns = [c.lower() for c in df.columns]
    print("Columns:", list(df.columns))

    required = ["close", "high", "low"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"В CSV отсутствует столбец: {col}")

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    # Presets override params (for reproducible runs)
    preset = (args.preset or "custom").strip().lower()
    if preset != "custom":
        p = _preset_params(preset)
        # apply only keys present
        for k, v in p.items():
            setattr(args, k, v)
        print(f"[preset] using {preset}: {p}")

    print("Computing indicators...")
    vi_plus, vi_minus = compute_vortex(high, low, close, args.vortex_period)
    rsi = compute_rsi(close, args.rsi_period)
    ema = compute_ema(close, args.ema_period)
    atr = compute_atr(high, low, close, args.atr_period)

    print("Running strategy...")
    mode = (args.mode or "static").strip().lower()
    if mode == "adaptive":
        # Индикаторы для двух наборов (trend/bear) считаются заранее, а выбор делается на каждом баре по regime[t].
        upper_t, lower_t, mid_t = compute_donchian(high, low, period=40)
        upper_b, lower_b, mid_b = compute_donchian(high, low, period=55)
        regime = compute_regime(
            close=close,
            ema_period=250,
            slope_period=args.regime_slope_period,
            lookback=args.regime_lookback,
            threshold=args.regime_threshold,
        )
        returns, positions = adaptive_strategy(
            close=close,
            high=high,
            low=low,
            vi_plus=vi_plus,
            vi_minus=vi_minus,
            upper_trend=upper_t,
            lower_trend=lower_t,
            mid_trend=mid_t,
            upper_bear=upper_b,
            lower_bear=lower_b,
            mid_bear=mid_b,
            rsi=rsi,
            ema=compute_ema(close, 250),
            atr=atr,
            regime=regime,
            rsi_long_trend=60.0,
            rsi_long_bear=60.0,
            rsi_short_bear=35.0,
            cost_bps=args.cost_bps,
        )
    else:
        upper, lower, mid = compute_donchian(high, low, args.donchian_period)
        returns, positions = strategy(
            close=close,
            high=high,
            low=low,
            vi_plus=vi_plus,
            vi_minus=vi_minus,
            upper=upper,
            lower=lower,
            mid=mid,
            rsi=rsi,
            ema=ema,
            atr=atr,
            rsi_long=args.rsi_long,
            rsi_short=args.rsi_short,
            allow_short=bool(args.allow_short),
            short_mode=args.short_mode,
            ema_slope_period=args.ema_slope_period,
            ema_slope_threshold=args.ema_slope_threshold,
            cost_bps=args.cost_bps,
        )

    print("Calculating metrics...")
    sharpe, total_sum = sharpe_and_sum(returns)
    cagr = calculate_cagr(returns, args.bars_per_year)
    max_dd = calculate_max_drawdown(returns)
    profit_factor = calculate_profit_factor(returns)
    equity = (1.0 + returns.fillna(0.0)).cumprod()

    trades_count = int((positions.diff().fillna(0) != 0).sum())
    long_bars = int((positions == 1).sum())

    print("Результаты стратегии Vortex + Donchian + RSI + ATR")
    print(f"  Sharpe: {sharpe:.4f}")
    print(f"  Sum: {total_sum:.4f}")
    print(f"  CAGR: {cagr:.2%}")
    print(f"  Max Drawdown: {max_dd:.2%}")
    print(f"  Profit Factor: {profit_factor:.4f}")
    print(f"  Final equity: {equity.iloc[-1]:.4f}")
    print(f"  Trades count: {trades_count}")
    print(f"  Long bars: {long_bars}")
    print(f"  Short bars: {int((positions == -1).sum())}")


if __name__ == "__main__":
    main()