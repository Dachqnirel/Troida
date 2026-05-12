import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("TINKOFF_TOKEN", "test_token")  # must be before any api import

# tinkoff-investments is not available in the test environment.
# Inject stubs so tAPI.py can be imported without the real SDK.
for _mod in [
    "tinkoff",
    "tinkoff.invest",
    "tinkoff.invest.schemas",
    "tinkoff.invest.caching",
    "tinkoff.invest.caching.instruments_cache",
    "tinkoff.invest.caching.instruments_cache.instruments_cache",
    "tinkoff.invest.caching.instruments_cache.settings",
    "tinkoff.invest.utils",
]:
    sys.modules.setdefault(_mod, MagicMock())

import pytest
from httpx import AsyncClient, ASGITransport
from api.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
