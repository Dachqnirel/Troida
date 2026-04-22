from pathlib import Path

import yaml

from src.config import (
    BrokerConfig,
    DataConfig,
    FuturesBacktestConfig,
    RuntimeConfig,
    StrategyConfig,
)


def _resolve_path(base_directory: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    return (base_directory / candidate).resolve()


def parseConfigFile(configPath: str) -> FuturesBacktestConfig:
    config_file = Path(configPath).expanduser().resolve()
    if not config_file.exists():
        raise FileNotFoundError(f"Конфигурационный файл не найден: {config_file}")

    with open(config_file, encoding="utf-8", mode="r") as file:
        raw_config = yaml.safe_load(file) or {}

    data_section = raw_config.get("data", {})
    broker_section = raw_config.get("broker", {})
    strategy_section = raw_config.get("strategy", {})
    runtime_section = raw_config.get("backtest", {})

    if "path" not in data_section:
        raise ValueError("В конфигурации отсутствует data.path")

    data_path = _resolve_path(config_file.parent, data_section["path"])
    instrument_name = raw_config.get("instrument_name", data_path.stem)

    data_config = DataConfig(
        path=data_path,
        format=str(data_section.get("format", data_path.suffix.lstrip("."))),
        drop_non_present_bars=bool(data_section.get("drop_non_present_bars", True)),
    )
    broker_config = BrokerConfig(
        starting_cash=float(broker_section.get("starting_cash", 500_000.0)),
        commission=float(broker_section.get("commission", 15.0)),
        margin=float(broker_section.get("margin", 15_000.0)),
        multiplier=float(broker_section.get("multiplier", 10.0)),
    )
    strategy_config = StrategyConfig(
        contracts=max(1, int(strategy_section.get("contracts", 1))),
        allow_short=bool(strategy_section.get("allow_short", True)),
        psar_period=max(2, int(strategy_section.get("psar_period", 2))),
        psar_af=float(strategy_section.get("psar_af", 0.02)),
        psar_afmax=float(strategy_section.get("psar_afmax", 0.2)),
        ema_period=max(2, int(strategy_section.get("ema_period", 50))),
        margin_buffer=max(1.0, float(strategy_section.get("margin_buffer", 1.05))),
    )
    runtime_config = RuntimeConfig(
        plot=bool(runtime_section.get("plot", False)),
    )

    return FuturesBacktestConfig(
        instrument_name=str(instrument_name),
        data=data_config,
        broker=broker_config,
        strategy=strategy_config,
        runtime=runtime_config,
    )
