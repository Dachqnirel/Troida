
# кэш для инструментов Т-инвестиций. Вызове функций InstrumentsService.shares() InstrumentsService.bounds() и.т.д слишком дорогие, поэтому их нужно кешировать
from asyncio import Semaphore
_INSTRUMENTS_CACHE: dict = {}
semaphoreForAccessCache: Semaphore = Semaphore(1)