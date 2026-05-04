import aiosqlite
from loguru import logger


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        import os
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info("数据库连接成功: {}", self.db_path)

    async def _create_tables(self):
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                book_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                category TEXT DEFAULT '',
                status TEXT DEFAULT '',
                word_count INTEGER DEFAULT 0,
                description TEXT DEFAULT '',
                cover_url TEXT DEFAULT '',
                total_recommend INTEGER DEFAULT 0,
                total_clicks INTEGER DEFAULT 0,
                total_favorites INTEGER DEFAULT 0,
                monthly_ticket INTEGER DEFAULT 0,
                rating_score REAL DEFAULT 0.0,
                is_vip INTEGER DEFAULT 0,
                latest_chapter_title TEXT DEFAULT '',
                update_time TEXT DEFAULT '',
                scraped_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS chapters (
                chapter_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                idx INTEGER DEFAULT 0,
                title TEXT DEFAULT '',
                is_vip INTEGER DEFAULT 0,
                word_count INTEGER DEFAULT 0,
                content TEXT DEFAULT '',
                content_scraped INTEGER DEFAULT 0,
                scraped_at TEXT DEFAULT '',
                PRIMARY KEY (chapter_id, book_id),
                FOREIGN KEY (book_id) REFERENCES books(book_id)
            );

            CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
        """)
        await self.conn.commit()

    async def upsert_book(self, book_data: dict):
        cols = ", ".join(book_data.keys())
        placeholders = ", ".join("?" for _ in book_data)
        updates = ", ".join(f"{k} = excluded.{k}" for k in book_data)
        sql = f"INSERT INTO books ({cols}) VALUES ({placeholders}) ON CONFLICT(book_id) DO UPDATE SET {updates}"
        await self.conn.execute(sql, list(book_data.values()))
        await self.conn.commit()

    async def upsert_chapter(self, chapter_data: dict):
        cols = ", ".join(chapter_data.keys())
        placeholders = ", ".join("?" for _ in chapter_data)
        updates = ", ".join(f"{k} = excluded.{k}" for k in chapter_data)
        sql = f"INSERT INTO chapters ({cols}) VALUES ({placeholders}) ON CONFLICT(chapter_id, book_id) DO UPDATE SET {updates}"
        await self.conn.execute(sql, list(chapter_data.values()))
        await self.conn.commit()

    async def get_book(self, book_id: int) -> dict | None:
        async with self.conn.execute("SELECT * FROM books WHERE book_id = ?", (book_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_chapters(self, book_id: int) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM chapters WHERE book_id = ? ORDER BY idx", (book_id,)
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def chapter_exists(self, book_id: int, chapter_id: int) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM chapters WHERE book_id = ? AND chapter_id = ? AND content_scraped = 1",
            (book_id, chapter_id),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def close(self):
        if self.conn:
            await self.conn.close()
            logger.info("数据库已关闭")
