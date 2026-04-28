from datetime import datetime
from typing import Any

from src.config import FuturesBacktestConfig


def _nested_get(data: Any, path: tuple[str, ...], default: Any = None) -> Any:
    current = data
    for key in path:
        if current is None:
            return default

        if hasattr(current, key):
            current = getattr(current, key)
            continue

        if isinstance(current, dict):
            current = current.get(key, default)
            continue

        try:
            current = current[key]
        except Exception:
            return default

    return current


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_run_summary(
    strategy: Any,
    config: FuturesBacktestConfig,
    bars_loaded: int,
    data_start: datetime,
    data_end: datetime,
) -> dict[str, Any]:
    broker_value = round(float(strategy.broker.getvalue()), 2)
    starting_cash = round(float(config.broker.starting_cash), 2)
    pnl_absolute = round(broker_value - starting_cash, 2)
    pnl_percent = round((pnl_absolute / starting_cash) * 100, 2) if starting_cash else 0.0

    trade_analysis = strategy.analyzers.trade_analyzer.get_analysis()
    drawdown_analysis = strategy.analyzers.drawdown.get_analysis()
    sharpe_analysis = strategy.analyzers.sharpe.get_analysis()
    returns_analysis = strategy.analyzers.returns.get_analysis()

    total_closed = int(_to_float(_nested_get(trade_analysis, ("total", "closed")), 0.0))
    won_total = int(_to_float(_nested_get(trade_analysis, ("won", "total")), 0.0))
    lost_total = int(_to_float(_nested_get(trade_analysis, ("lost", "total")), 0.0))
    win_rate = round((won_total / total_closed) * 100, 2) if total_closed else 0.0

    return {
        "instrument_name": config.instrument_name,
        "data_path": str(config.data.path),
        "bars_loaded": bars_loaded,
        "period": {
            "from": data_start.isoformat(),
            "to": data_end.isoformat(),
        },
        "broker": {
            "starting_cash": starting_cash,
            "ending_value": broker_value,
            "commission": config.broker.commission,
            "margin": config.broker.margin,
            "multiplier": config.broker.multiplier,
        },
        "strategy": {
            "name": strategy.__class__.__name__,
            "configured_name": config.strategy.name,
            "contracts": config.strategy.contracts,
            "allow_short": config.strategy.allow_short,
            "adx_period": config.strategy.adx_period,
            "adx_entry_level": config.strategy.adx_entry_level,
            "adx_exit_level": config.strategy.adx_exit_level,
            "psar_period": config.strategy.psar_period,
            "psar_af": config.strategy.psar_af,
            "psar_afmax": config.strategy.psar_afmax,
            "ema_period": config.strategy.ema_period,
            "atr_period": config.strategy.atr_period,
            "atr_stop_multiplier": config.strategy.atr_stop_multiplier,
        },
        "performance": {
            "pnl_absolute": pnl_absolute,
            "pnl_percent": pnl_percent,
            "max_drawdown_percent": round(
                _to_float(_nested_get(drawdown_analysis, ("max", "drawdown")), 0.0),
                2,
            ),
            "max_drawdown_money": round(
                _to_float(_nested_get(drawdown_analysis, ("max", "moneydown")), 0.0),
                2,
            ),
            "sharpe_ratio": round(
                _to_float(_nested_get(sharpe_analysis, ("sharperatio",)), 0.0),
                4,
            ),
            "returns_total": round(
                _to_float(_nested_get(returns_analysis, ("rtot",)), 0.0),
                4,
            ),
        },
        "trades": {
            "total_closed": total_closed,
            "won": won_total,
            "lost": lost_total,
            "win_rate_percent": win_rate,
            "orders_executed": len(getattr(strategy, "executed_orders", [])),
        },
        "closed_trades_log": getattr(strategy, "closed_trades", []),
    }


def format_run_summary(summary: dict[str, Any]) -> str:
    broker = summary["broker"]
    performance = summary["performance"]
    trades = summary["trades"]
    strategy = summary["strategy"]
    period = summary["period"]
    if strategy["configured_name"] == "psar":
        strategy_params = (
            f"name={strategy['name']}, "
            f"contracts={strategy['contracts']}, "
            f"allow_short={strategy['allow_short']}, "
            f"psar=({strategy['psar_period']}, {strategy['psar_af']}, {strategy['psar_afmax']}), "
            f"ema={strategy['ema_period']}"
        )
    else:
        strategy_params = (
            f"name={strategy['name']}, "
            f"contracts={strategy['contracts']}, "
            f"allow_short={strategy['allow_short']}, "
            f"adx=({strategy['adx_period']}, entry={strategy['adx_entry_level']}, "
            f"exit={strategy['adx_exit_level']}), "
            f"ema={strategy['ema_period']}, "
            f"atr_stop=({strategy['atr_period']}, x{strategy['atr_stop_multiplier']})"
        )

    lines = [
        "===== Итоги фьючерсного бэктеста =====",
        f"Инструмент: {summary['instrument_name']}",
        f"Период данных: {period['from']} -> {period['to']}",
        f"Свечей загружено: {summary['bars_loaded']}",
        f"Стартовый капитал: {broker['starting_cash']:.2f}",
        f"Итоговая стоимость портфеля: {broker['ending_value']:.2f}",
        f"PnL: {performance['pnl_absolute']:.2f} ({performance['pnl_percent']:.2f}%)",
        (
            "Фьючерсные параметры брокера: "
            f"commission={broker['commission']}, "
            f"margin={broker['margin']}, "
            f"multiplier={broker['multiplier']}"
        ),
        f"Параметры стратегии: {strategy_params}",
        (
            "Сделки: "
            f"closed={trades['total_closed']}, "
            f"won={trades['won']}, "
            f"lost={trades['lost']}, "
            f"win_rate={trades['win_rate_percent']:.2f}%"
        ),
        (
            "Риск-метрики: "
            f"max_dd={performance['max_drawdown_percent']:.2f}%, "
            f"money_dd={performance['max_drawdown_money']:.2f}, "
            f"sharpe={performance['sharpe_ratio']:.4f}, "
            f"returns_total={performance['returns_total']:.4f}"
        ),
    ]

    return "\n".join(lines)
