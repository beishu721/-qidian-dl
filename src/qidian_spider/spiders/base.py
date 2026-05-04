import random
import asyncio
from abc import ABC
from loguru import logger
from ..browser.manager import BrowserManager
from ..storage.database import Database
from ..config import settings


class BaseSpider(ABC):
    def __init__(self, browser: BrowserManager, db: Database):
        self.browser = browser
        self.db = db

    async def delay(self):
        """随机延迟，避免被检测"""
        t = random.uniform(
            settings.rate_limit.min_delay_seconds,
            settings.rate_limit.max_delay_seconds,
        )
        await asyncio.sleep(t)
