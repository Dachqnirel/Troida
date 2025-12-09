from dataclasses import dataclass
from datetime import datetime

@dataclass(init=True)
class DividendConfig:
    """
    Конфигурация для отчёта по дивидендам: тикер, период.
    """
    ticker: str
    from_date: datetime
    to_date: datetime
