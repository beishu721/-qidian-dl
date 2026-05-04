from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class BookStatus(str, Enum):
    ONGOING = "连载"
    COMPLETED = "完本"


class Chapter(BaseModel):
    chapter_id: int
    book_id: int
    index: int = 0
    title: str
    is_vip: bool = False
    word_count: int = 0
    content: str = ""
    content_scraped: bool = False
    scraped_at: datetime = Field(default_factory=datetime.now)


class Book(BaseModel):
    book_id: int
    title: str
    author: str = ""
    category: str = ""
    status: BookStatus | None = None
    word_count: int = 0
    description: str = ""
    cover_url: str = ""

    total_recommend: int = 0
    total_clicks: int = 0
    total_favorites: int = 0
    monthly_ticket: int = 0
    rating_score: float = 0.0

    is_vip: bool = False
    latest_chapter_title: str = ""
    update_time: str = ""

    chapters: list[Chapter] = []
    scraped_at: datetime = Field(default_factory=datetime.now)
