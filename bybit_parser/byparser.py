from pybit.unified_trading import HTTP
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from typing import Optional
import argparse
import csv
import logging
import os
import statistics


# ─────────────────────────── Константы ───────────────────────────────

INTERVAL_MINUTES: dict[str, int] = {
    "1": 1, "3": 3, "5": 5, "15": 15, "30": 30,
    "60": 60, "120": 120, "240": 240, "360": 360, "720": 720,
    "D": 1440, "W": 10080, "M": 43200,
}

VALID_INTERVALS  = list(INTERVAL_MINUTES.keys())
VALID_CATEGORIES = ["spot", "linear", "inverse"]


# ─────────────────────────── Логирование ─────────────────────────────

def setup_logger() -> logging.Logger:
    load_dotenv()

    log_dir    = os.getenv("LOG_PATH", "logs")
    max_bytes  = int(os.getenv("LOG_FILE_SIZE", 5 * 1024 * 1024))
    backup_cnt = int(os.getenv("BACKUP_FILES_COUNT", 5))

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "byparser.log")

    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_cnt, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.INFO)

    log = logging.getLogger("byparser")
    log.setLevel(logging.DEBUG)
    log.addHandler(file_handler)
    log.addHandler(console_handler)

    return log


logger = setup_logger()


# ─────────────────────────── Bybit клиент ────────────────────────────

class BybitCandles:
    def __init__(self):
        self.session = HTTP()

    def get_candles(
        self,
        symbol:    str,
        interval:  str,
        category:  str  = "spot",
        limit:     int  = 200,
        start_ms:  int  | None = None,
        end_ms:    int  | None = None,
    ) -> list[dict] | None:
        if start_ms or end_ms:
            return self._get_range(symbol, interval, category, start_ms, end_ms)
        return self._get_last(symbol, interval, category, limit)

    def _get_last(self, symbol, interval, category, limit):
        logger.info("Запрос последних %d свеч: %s | %s | %s", limit, symbol, category, interval)
        try:
            response = self.session.get_kline(
                category=category, symbol=symbol, interval=interval, limit=limit,
            )
            if response["retCode"] == 0:
                candles = self._format(response["result"]["list"])
                logger.info("Получено %d свеч", len(candles))
                return candles
            logger.error("Bybit вернул ошибку: %s", response["retMsg"])
            return None
        except Exception as e:
            logger.exception("Исключение при запросе к Bybit: %s", e)
            return None

    def _get_range(self, symbol, interval, category, start_ms, end_ms):
        start_str = datetime.fromtimestamp(start_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if start_ms else "—"
        end_str   = datetime.fromtimestamp(end_ms   / 1000).strftime("%Y-%m-%d %H:%M:%S") if end_ms   else "сейчас"
        logger.info("Запрос диапазона: %s | %s | %s  [%s → %s]",
                    symbol, category, interval, start_str, end_str)

        all_candles: list[dict] = []
        current_end = end_ms
        page = 0

        while True:
            page += 1
            try:
                kwargs: dict = dict(category=category, symbol=symbol, interval=interval, limit=200)
                if start_ms:
                    kwargs["start"] = start_ms
                if current_end:
                    kwargs["end"] = current_end

                response = self.session.get_kline(**kwargs)
                if response["retCode"] != 0:
                    logger.error("Bybit ошибка (страница %d): %s", page, response["retMsg"])
                    break

                batch = self._format(response["result"]["list"])
                if not batch:
                    break

                logger.debug("Страница %d: получено %d свеч (до %s)", page, len(batch), batch[-1]["datetime"])

                all_candles = batch + all_candles

                if len(batch) < 200:
                    break

                current_end = batch[0]["timestamp"] - 1

                if start_ms and current_end < start_ms:
                    break

            except Exception as e:
                logger.exception("Исключение при пагинации (страница %d): %s", page, e)
                break

        if start_ms:
            all_candles = [c for c in all_candles if c["timestamp"] >= start_ms]
        if end_ms:
            all_candles = [c for c in all_candles if c["timestamp"] <= end_ms]

        logger.info("Всего получено %d свеч за %d запрос(а)", len(all_candles), page)
        return all_candles if all_candles else None

    @staticmethod
    def _format(raw: list) -> list[dict]:
        candles = []
        for c in raw:
            candles.append({
                "timestamp": int(c[0]),
                "datetime":  datetime.fromtimestamp(int(c[0]) / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                "open":      float(c[1]),
                "high":      float(c[2]),
                "low":       float(c[3]),
                "close":     float(c[4]),
                "volume":    float(c[5]),
                "turnover":  float(c[6]) if len(c) > 6 else 0.0,
            })
        return candles[::-1]


# ─────────────────────────── Детектор аномалий ───────────────────────

class AnomalyDetector:
    Z_THRESHOLD = 3.0
    WINDOW      = 20

    def __init__(self, interval_minutes: int):
        self.interval_ms = interval_minutes * 60 * 1000

    def check_and_fix(self, candles: list[dict]) -> tuple[list[dict], int]:
        before   = len(candles)
        candles  = self._fix_duplicates(candles)
        candles  = self._fix_ohlc(candles)
        candles  = self._fix_zero_volume(candles)
        candles  = self._fix_price_spikes(candles)
        self._report_gaps(candles)
        removed  = before - len(candles)
        logger.info("Проверка завершена: осталось %d свеч, удалено %d", len(candles), removed)
        return candles, removed

    def _fix_duplicates(self, candles):
        seen, unique = set(), []
        for c in candles:
            if c["timestamp"] in seen:
                logger.warning("[ДУБЛЬ]   удалена свеча %s", c["datetime"])
            else:
                seen.add(c["timestamp"])
                unique.append(c)
        return unique

    def _fix_ohlc(self, candles):
        fixed = []
        for c in candles.copy():
            issues = []
            real_high = max(c["open"], c["close"], c["high"])
            if c["high"] < real_high:
                issues.append(f"high {c['high']} < max(O,C)={real_high}")
                c["high"] = real_high
            real_low = min(c["open"], c["close"], c["low"])
            if c["low"] > real_low:
                issues.append(f"low {c['low']} > min(O,C)={real_low}")
                c["low"] = real_low
            if c["high"] < c["low"]:
                issues.append(f"high {c['high']} < low {c['low']} — удалена")
                logger.warning("[OHLC]    %s: %s", c["datetime"], "; ".join(issues))
                continue
            if issues:
                logger.warning("[OHLC]    %s: исправлено — %s", c["datetime"], "; ".join(issues))
            fixed.append(c)
        return fixed

    def _fix_zero_volume(self, candles):
        clean = []
        for c in candles:
            if c["volume"] <= 0:
                logger.warning("[ОБЪЁМ]   %s: объём=%s — удалена", c["datetime"], c["volume"])
            else:
                clean.append(c)
        return clean

    def _fix_price_spikes(self, candles):
        if len(candles) < self.WINDOW:
            return candles
        skip   = set()
        closes = [c["close"] for c in candles]
        for i in range(len(candles)):
            lo     = max(0, i - self.WINDOW // 2)
            hi     = min(len(candles), i + self.WINDOW // 2)
            window = closes[lo:hi]
            if len(window) < 4:
                continue
            mean  = statistics.mean(window)
            stdev = statistics.stdev(window)
            if stdev == 0:
                continue
            z = abs(closes[i] - mean) / stdev
            if z > self.Z_THRESHOLD:
                skip.add(i)
                logger.warning("[ВЫБРОС]  %s: close=%.4f, Z=%.2f (порог %.1f) — удалена",
                               candles[i]["datetime"], candles[i]["close"], z, self.Z_THRESHOLD)
        return [c for i, c in enumerate(candles) if i not in skip]

    def _report_gaps(self, candles):
        if self.interval_ms == 0:
            return
        threshold = self.interval_ms * 2
        for i in range(1, len(candles)):
            delta = candles[i]["timestamp"] - candles[i - 1]["timestamp"]
            if delta > threshold:
                missing = delta // self.interval_ms - 1
                logger.warning("[ПРОПУСК] после %s: пропущено ~%d свеч(и)",
                               candles[i - 1]["datetime"], missing)


# ─────────────────────────── CSV-экспорт ─────────────────────────────

FIELDS = ["timestamp", "datetime", "open", "high", "low", "close", "volume", "turnover"]


def save_csv(candles: list[dict], filepath: str) -> None:
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(candles)
    logger.info("CSV сохранён: %s (%d свеч)", os.path.abspath(filepath), len(candles))


# ─────────────────────────── Утилиты ─────────────────────────────────

def parse_date(value: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(value, fmt).timestamp() * 1000)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Неверный формат даты: '{value}'. Используйте YYYY-MM-DD или 'YYYY-MM-DD HH:MM:SS'"
    )


def fetch_and_clean(
    symbol: str,
    interval: str,
    category: str = "spot",
    limit: int = 200,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> list[dict]:
    """Общая логика: получить свечи + очистить аномалии."""
    candles = BybitCandles().get_candles(
        symbol=symbol, interval=interval, category=category,
        limit=limit, start_ms=start_ms, end_ms=end_ms,
    )
    if not candles:
        return []
    cleaned, _ = AnomalyDetector(INTERVAL_MINUTES.get(interval, 60)).check_and_fix(candles)
    return cleaned


# ─────────────────────────── HTTP-сервер (FastAPI) ────────────────────

def create_app():
    from fastapi import FastAPI, Query, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI(
        title="Bybit Candles API",
        description="GET /candles — получить свечи с Bybit",
        version="1.0.0",
    )

    @app.get("/candles")
    def get_candles(
        symbol:   str = Query(...,  description="Торговая пара: BTCUSDT, ETHUSDT и т.д."),
        interval: str = Query(...,  description=f"Таймфрейм: {', '.join(VALID_INTERVALS)}"),
        category: str = Query("spot", description=f"Тип рынка: {', '.join(VALID_CATEGORIES)}"),
        limit:    int = Query(200,  ge=1, le=200, description="Кол-во свечей (без диапазона, макс 200)"),
        start:    Optional[str] = Query(None, description="Начало диапазона: YYYY-MM-DD или YYYY-MM-DD HH:MM:SS (UTC)"),
        end:      Optional[str] = Query(None, description="Конец диапазона:  YYYY-MM-DD или YYYY-MM-DD HH:MM:SS (UTC)"),
    ):
        """
        Вернуть свечи в JSON.

        Примеры:
        - `/candles?symbol=BTCUSDT&interval=60&category=spot&limit=100`
        - `/candles?symbol=ETHUSDT&interval=15&category=linear&start=2024-01-01&end=2024-02-01`
        """
        symbol = symbol.upper()

        if interval not in VALID_INTERVALS:
            raise HTTPException(status_code=400, detail=f"interval должен быть одним из: {VALID_INTERVALS}")
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"category должен быть одним из: {VALID_CATEGORIES}")

        start_ms = None
        end_ms   = None
        if start:
            try:
                start_ms = parse_date(start)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Неверный формат start: '{start}'")
        if end:
            try:
                end_ms = parse_date(end)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Неверный формат end: '{end}'")

        candles = fetch_and_clean(
            symbol=symbol, interval=interval, category=category,
            limit=limit, start_ms=start_ms, end_ms=end_ms,
        )

        if not candles:
            raise HTTPException(status_code=404, detail="Свечи не получены. Проверьте параметры.")

        return JSONResponse(content={"count": len(candles), "candles": candles})

    return app


# ─────────────────────────── Argparse ────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="byparser",
        description="Парсер свечей Bybit. Режимы: CLI (--symbol ...) или HTTP-сервер (--serve).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # HTTP-сервер на порту 8000
  python byparser.py --serve

  # HTTP-сервер на своём порту
  python byparser.py --serve --host 0.0.0.0 --port 9000

  # CLI: последние 200 часовых свечей BTC (спот)
  python byparser.py -s BTCUSDT -c spot -i 60 -l 200 -o btc.csv

  # CLI: все 15-минутные свечи ETH (фьючерс) за январь 2024
  python byparser.py -s ETHUSDT -c linear -i 15 --start 2024-01-01 --end 2024-02-01 -o eth.csv
        """,
    )

    # ── Режим сервера ────────────────────────────────────────────────
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Запустить HTTP-сервер (FastAPI + uvicorn)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="HOST",
        help="Адрес для HTTP-сервера (по умолчанию: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        metavar="PORT",
        help="Порт для HTTP-сервера (по умолчанию: 8000)",
    )

    # ── CLI-параметры ────────────────────────────────────────────────
    parser.add_argument("-s", "--symbol",   metavar="ПАРА",     help="Торговая пара: BTCUSDT, ETHUSDT и т.д.")
    parser.add_argument("-c", "--category", choices=VALID_CATEGORIES, help=f"Тип рынка: {', '.join(VALID_CATEGORIES)}")
    parser.add_argument("-i", "--interval", choices=VALID_INTERVALS,  metavar="ИНТЕРВАЛ", help=f"Таймфрейм: {', '.join(VALID_INTERVALS)}")
    parser.add_argument("--start", type=parse_date, metavar="ДАТА", help="Начало диапазона (UTC)")
    parser.add_argument("--end",   type=parse_date, metavar="ДАТА", help="Конец диапазона  (UTC)")
    parser.add_argument("-l", "--limit", type=int, default=200, metavar="N", help="Количество свечей без диапазона (1–200)")
    parser.add_argument("-o", "--output", metavar="ФАЙЛ", help="Путь для сохранения CSV")

    return parser


# ─────────────────────────── Main ────────────────────────────────────

def main():
    args = build_parser().parse_args()

    # ── Режим HTTP-сервера ───────────────────────────────────────────
    if args.serve:
        try:
            import uvicorn
        except ImportError:
            print("Для сервера установите зависимости: pip install fastapi uvicorn")
            return
        app = create_app()
        logger.info("Запуск HTTP-сервера на http://%s:%d  (документация: /docs)", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port)
        return

    # ── CLI-режим ────────────────────────────────────────────────────
    if not args.symbol or not args.category or not args.interval:
        build_parser().error("В CLI-режиме обязательны: -s/--symbol, -c/--category, -i/--interval")

    symbol   = args.symbol.upper()
    category = args.category
    interval = args.interval
    limit    = max(1, min(args.limit, 200))
    start_ms = args.start
    end_ms   = args.end
    out_file = args.output or f"{symbol}_{category}_{interval}.csv"

    logger.info(
        "Запуск CLI: symbol=%s  category=%s  interval=%s  limit=%s  start=%s  end=%s  output=%s",
        symbol, category, interval,
        limit if not (start_ms or end_ms) else "—(диапазон)",
        datetime.fromtimestamp(start_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if start_ms else "—",
        datetime.fromtimestamp(end_ms   / 1000).strftime("%Y-%m-%d %H:%M:%S") if end_ms   else "—",
        out_file,
    )

    cleaned = fetch_and_clean(
        symbol=symbol, interval=interval, category=category,
        limit=limit, start_ms=start_ms, end_ms=end_ms,
    )

    if not cleaned:
        logger.error("Свечи не получены. Проверьте параметры.")
        return

    save_csv(cleaned, out_file)


if __name__ == "__main__":
    main()
