from dataclasses import dataclass
from datetime import datetime
@dataclass(init=True)
class StockConfig():
    """
    DataClass для акции: тикер, интервал, от какой datetime парсинг свечей, до какой datetime парсинг свечей
    """    
    ticker: str # тикер
    interval: str # интервал
    from_date: datetime # от какой даты считывание
    to_date: datetime # до какой даты считывание
