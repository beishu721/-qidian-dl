from pydantic import BaseModel


class BrowserConfig(BaseModel):
    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080
    timeout_ms: int = 30000
    locale: str = "zh-CN"
    timezone_id: str = "Asia/Shanghai"


class RateLimitConfig(BaseModel):
    min_delay_seconds: float = 3.0
    max_delay_seconds: float = 8.0
    max_concurrent_pages: int = 2


class StorageConfig(BaseModel):
    db_path: str = "data/db/qidian.db"


class SpiderSettings(BaseModel):
    browser: BrowserConfig = BrowserConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()
    storage: StorageConfig = StorageConfig()
    log_level: str = "INFO"


settings = SpiderSettings()
