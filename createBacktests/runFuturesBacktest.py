import json
import sys
from pathlib import Path

import backtrader as bt

sys.path.append(str(Path(__file__).parent))

from src.data_loader import load_market_data
from src.parsers.arguments_cli import getOptionsFromCLI
from src.parsers.parse_config import parseConfigFile
from src.reporting import build_run_summary, format_run_summary
from src.strategies.futures_adx import FuturesADXStrategy
from src.strategies.futures_psar import FuturesParabolicSARStrategy


def _add_strategy(cerebro: bt.Cerebro, config, quiet: bool) -> None:
    common_params = {
        "contracts": config.strategy.contracts,
        "allow_short": config.strategy.allow_short,
        "ema_period": config.strategy.ema_period,
        "margin": config.broker.margin,
        "margin_buffer": config.strategy.margin_buffer,
        "printlog": not quiet,
    }

    if config.strategy.name == "adx":
        cerebro.addstrategy(
            FuturesADXStrategy,
            **common_params,
            adx_period=config.strategy.adx_period,
            adx_entry_level=config.strategy.adx_entry_level,
            adx_exit_level=config.strategy.adx_exit_level,
            atr_period=config.strategy.atr_period,
            atr_stop_multiplier=config.strategy.atr_stop_multiplier,
        )
        return

    if config.strategy.name == "psar":
        cerebro.addstrategy(
            FuturesParabolicSARStrategy,
            **common_params,
            psar_period=config.strategy.psar_period,
            psar_af=config.strategy.psar_af,
            psar_afmax=config.strategy.psar_afmax,
        )
        return

    raise ValueError(
        f"Неизвестная стратегия '{config.strategy.name}'. "
        "Используйте 'adx' или 'psar'."
    )


def main() -> None:
    arguments = getOptionsFromCLI()
    config = parseConfigFile(arguments.file)
    dataframe = load_market_data(config.data)

    cerebro = bt.Cerebro(stdstats=False)
    data_feed = bt.feeds.PandasData(dataname=dataframe)
    cerebro.adddata(data_feed, name=config.instrument_name)

    _add_strategy(cerebro, config, arguments.quiet)

    cerebro.broker.setcash(config.broker.starting_cash)
    cerebro.broker.setcommission(
        commission=config.broker.commission,
        margin=config.broker.margin,
        mult=config.broker.multiplier,
        name=config.instrument_name,
    )

    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    results = cerebro.run()
    strategy = results[0]

    summary = build_run_summary(
        strategy=strategy,
        config=config,
        bars_loaded=len(dataframe),
        data_start=dataframe.index.min().to_pydatetime(),
        data_end=dataframe.index.max().to_pydatetime(),
    )

    print(format_run_summary(summary))

    if arguments.output:
        output_path = Path(arguments.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON-отчёт сохранён в {output_path}")

    if arguments.plot or config.runtime.plot:
        cerebro.plot(style="candlestick")


if __name__ == "__main__":
    main()
