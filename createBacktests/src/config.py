from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DataConfig:
    path: Path
    format: str = "csv"
    drop_non_present_bars: bool = True


@dataclass(slots=True)
class BrokerConfig:
    starting_cash: float = 500_000.0
    commission: float = 15.0
    margin: float = 15_000.0
    multiplier: float = 10.0


@dataclass(slots=True)
class StrategyConfig:
    name: str = "adx"
    contracts: int = 1
    allow_short: bool = True
    adx_period: int = 14
    adx_entry_level: float = 25.0
    adx_exit_level: float = 20.0
    psar_period: int = 2
    psar_af: float = 0.02
    psar_afmax: float = 0.2
    ema_period: int = 50
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    margin_buffer: float = 1.05


@dataclass(slots=True)
class RuntimeConfig:
    plot: bool = False


@dataclass(slots=True)
class FuturesBacktestConfig:
    instrument_name: str
    data: DataConfig
    broker: BrokerConfig
    strategy: StrategyConfig
    runtime: RuntimeConfig
