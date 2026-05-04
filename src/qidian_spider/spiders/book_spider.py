import re
import asyncio
from datetime import datetime
from urllib.parse import urljoin

from loguru import logger
from playwright.async_api import Page

from .base import BaseSpider
from ..models.book import Book, Chapter, BookStatus


class BookSpider(BaseSpider):
    """单本书籍 + 章节爬虫"""

    BOOK_URL = "https://book.qidian.com/info/{book_id}/"
    CATALOG_URL = "https://book.qidian.com/info/{book_id}/#Catalog"

    async def scrape(self, book_id: int) -> Book:
        logger.info("=" * 50)
        logger.info("开始爬取书籍 ID={}", book_id)

        page = await self.browser.navigate_safe(self.BOOK_URL.format(book_id=book_id))

        # 提取书籍基本信息
        book_info = await self._extract_book_info(page, book_id)
        logger.info("书名: {}", book_info["title"])

        # 保存书籍信息
        await self.db.upsert_book(book_info)
        logger.info("书籍信息已保存")

        # 获取章节列表
        await self.delay()
        chapters = await self._extract_chapter_list(page, book_id)
        logger.info("发现 {} 章 (VIP: {})", len(chapters), sum(1 for c in chapters if c.is_vip))

        # 爬取章节内容
        if chapters:
            await self._scrape_chapters(page, book_id, chapters)

        await page.close()

        logger.info("完成爬取: {}", book_info["title"])
        logger.info("=" * 50)

        book = Book(
            book_id=book_id,
            title=book_info["title"],
            author=book_info.get("author", ""),
            category=book_info.get("category", ""),
            status=BookStatus.ONGOING if book_info.get("status") == "连载" else BookStatus.COMPLETED,
            word_count=book_info.get("word_count", 0),
            description=book_info.get("description", ""),
            chapters=chapters,
        )
        return book

    async def _extract_book_info(self, page: Page, book_id: int) -> dict:
        """从书籍详情页提取元信息"""
        info = {"book_id": book_id, "title": "", "scraped_at": datetime.now().isoformat()}

        try:
            # 尝试从页内 <script> 提取结构化数据
            script_data = await page.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script[type="text/javascript"], script:not([type])');
                    for (const s of scripts) {
                        const t = s.textContent || '';
                        if (t.includes('window.__NUXT__') || t.includes('window.__INITIAL_STATE__')) {
                            return t.substring(0, 50000);
                        }
                    }
                    return '';
                }
            """)

            if script_data:
                # 尝试提取 window.__INITIAL_STATE__ 或类似JSON
                m = re.search(
                    r'window\.__(?:NUXT__|INITIAL_STATE__)\s*=\s*({.+?});',
                    script_data,
                    re.DOTALL,
                )
                if m:
                    import json
                    try:
                        state = json.loads(m.group(1))
                        logger.debug("从页内JS提取到结构化数据")
                    except json.JSONDecodeError:
                        state = {}

        except Exception as e:
            logger.debug("提取页内数据失败: {}", e)

        # 书名
        title = await self.browser.extract_text_content(page, "h1")
        info["title"] = title or f"book_{book_id}"

        # 作者
        author = await self.browser.extract_text_content(page, "a.writer, .writer, a[href*='author']")
        info["author"] = author

        # 用 evaluate 更灵活地提取
        extra = await page.evaluate("""
            () => {
                const result = { category: '', status: '', word_count: 0, description: '' };

                // 提取所有文本，按标签层级查找
                const labels = document.querySelectorAll('.detail-wrap .cf li, .book-info .tag');
                labels.forEach(el => {
                    const text = el.innerText || '';
                    if (text.includes('分类') || text.includes('类型')) {
                        result.category = text.replace(/分类|类型|：|:/g, '').trim();
                    }
                    if (text.includes('连载') || text.includes('完本')) {
                        result.status = text.includes('完本') ? '完本' : '连载';
                    }
                    if (text.includes('字') && /\\d/.test(text)) {
                        const match = text.match(/([\\d.]+)万?字/);
                        if (match) {
                            const n = parseFloat(match[1]);
                            result.word_count = text.includes('万') ? Math.floor(n * 10000) : Math.floor(n);
                        }
                    }
                });

                // 简介
                const desc = document.querySelector('.intro, .book-intro, .about-text, .book-brief');
                if (desc) result.description = desc.innerText.trim();

                return result;
            }
        """)
        info["category"] = extra.get("category", "")
        info["status"] = extra.get("status", "")
        info["word_count"] = extra.get("word_count", 0)
        info["description"] = extra.get("description", "")

        return info

    async def _extract_chapter_list(self, page: Page, book_id: int) -> list[Chapter]:
        """从页面提取章节列表"""
        chapters: list[Chapter] = []

        try:
            # 起点目录页通常可以通过修改URL访问
            catalog_url = f"https://book.qidian.com/info/{book_id}/#Catalog"
            await page.goto(catalog_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # 通过JS提取章节数据
            chapter_data = await page.evaluate("""
                () => {
                    const chapters = [];
                    // 尝试多种选择器适配不同页面结构
                    const items = document.querySelectorAll(
                        '.catalog-content li, .chapter-list li, [data-rid], .volume-list li'
                    );
                    items.forEach((el, idx) => {
                        const link = el.querySelector('a');
                        const href = link ? link.getAttribute('href') : '';
                        const title = link ? link.innerText.trim() : el.innerText.trim();
                        const isVip = el.classList.contains('vip') ||
                                      (el.querySelector('.vip, .icon-vip') !== null) ||
                                      (el.innerText || '').includes('VIP');

                        // 从 href 提取 chapter_id
                        let chapterId = '';
                        if (href) {
                            const m = href.match(/(\\d+)/);
                            if (m) chapterId = m[1];
                        }

                        if (title && chapterId) {
                            chapters.push({
                                chapter_id: parseInt(chapterId),
                                title: title,
                                is_vip: isVip,
                                index: idx
                            });
                        }
                    });
                    return chapters;
                }
            """)

            for c in chapter_data:
                chapters.append(Chapter(
                    chapter_id=c["chapter_id"],
                    book_id=book_id,
                    index=c["index"],
                    title=c["title"],
                    is_vip=c["is_vip"],
                ))

            # 如果DOM没提取到，尝试从API或script标签提取
            if not chapters:
                logger.debug("DOM未提取到章节，尝试从页面数据提取...")
                chapters = await self._extract_chapters_from_script(page, book_id)

        except Exception as e:
            logger.error("提取章节列表失败: {}", e)
            chapters = await self._extract_chapters_from_script(page, book_id)

        return chapters

    async def _extract_chapters_from_script(self, page: Page, book_id: int) -> list[Chapter]:
        """从页面 script 中提取章节数据作为后备方案"""
        chapters: list[Chapter] = []
        try:
            data = await page.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script');
                    for (const s of scripts) {
                        const t = s.textContent || '';
                        if (t.includes('chapterList') || t.includes('chapter_list') || t.includes('chapters')) {
                            return t.substring(0, 100000);
                        }
                    }
                    return '';
                }
            """)

            if data:
                # 尝试匹配 chapterList 数组
                m = re.search(r'"(?:chapterList|chapter_list|chapters)"\s*:\s*(\[.+?\])', data, re.DOTALL)
                if m:
                    import json
                    try:
                        cl = json.loads(m.group(1))
                        for i, c in enumerate(cl):
                            chapters.append(Chapter(
                                chapter_id=int(c.get("id", c.get("chapterId", 0))),
                                book_id=book_id,
                                index=i,
                                title=c.get("name", c.get("title", "")),
                                is_vip=c.get("isVip", c.get("is_vip", False)),
                                word_count=c.get("wordCount", c.get("word_count", 0)),
                            ))
                    except (json.JSONDecodeError, ValueError):
                        pass
        except Exception as e:
            logger.debug("从script提取章节也失败: {}", e)

        return chapters

    async def _scrape_chapters(self, page: Page, book_id: int, chapters: list[Chapter]):
        """爬取各章节正文内容"""
        total = len(chapters)
        success = 0
        chapter_url_base = f"https://www.qidian.com/chapter/{book_id}/"

        # 先获取免费章节的URL结构
        for i, ch in enumerate(chapters, 1):
            already_done = await self.db.chapter_exists(book_id, ch.chapter_id)
            if already_done:
                logger.debug("[{}/{}] 跳过已爬取章节: {}", i, total, ch.title)
                continue

            await self.delay()

            try:
                content = await self._extract_chapter_content(page, book_id, ch)
                if content:
                    await self.db.upsert_chapter({
                        "chapter_id": ch.chapter_id,
                        "book_id": book_id,
                        "idx": ch.index,
                        "title": ch.title,
                        "is_vip": 1 if ch.is_vip else 0,
                        "word_count": ch.word_count or len(content),
                        "content": content,
                        "content_scraped": 1,
                        "scraped_at": datetime.now().isoformat(),
                    })
                    success += 1
                    logger.info("[{}/{}] ✓ {} ({}字)", i, total, ch.title[:30], len(content))
                else:
                    logger.warning("[{}/{}] ✗ 内容为空: {} (VIP={})", i, total, ch.title[:30], ch.is_vip)
            except Exception as e:
                logger.error("[{}/{}] ✗ 爬取失败: {} - {}", i, total, ch.title[:30], e)

            # 每10章短暂休息，降低被封风险
            if i % 10 == 0:
                logger.info("已处理 {} 章，休息 10 秒...", i)
                await asyncio.sleep(10)

        logger.info("章节爬取完成: {}/{} 成功", success, total)

    async def _extract_chapter_content(self, page: Page, book_id: int, chapter: Chapter) -> str:
        """提取单个章节的正文内容"""
        # 起点章节URL — 用 read.qidian.com 域名更稳定
        chapter_url = f"https://read.qidian.com/chapter/{book_id}/{chapter.chapter_id}/"

        try:
            book_url = f"https://book.qidian.com/info/{book_id}/"
            await page.goto(chapter_url, referer=book_url, wait_until="networkidle", timeout=45000)
            await asyncio.sleep(1.5)

            # 用标题判断是否被拦截（和首页修复方式一致，避免WAF脚本误报）
            page_title = await page.title()
            if "安全验证" in page_title or "Access Denied" in page_title:
                logger.warning("章节 {} 被WAF拦截", chapter.index + 1)
                return ""

            # 提取正文 - 尝试多种选择器
            selectors = [
                ".read-content",           # 起点标准内容区
                ".content",                # 备用
                "#chapter-content",        # 备用
                ".text-wrap",              # 备用
                "article",                 # 通用
            ]

            content = ""
            for sel in selectors:
                try:
                    text = await page.eval_on_selector(
                        sel,
                        "el => el.innerText",
                    )
                    if text and len(text.strip()) > 50:
                        content = text.strip()
                        break
                except Exception:
                    continue

            if not content:
                # 最终尝试 - 获取 body 中最大文本块
                content = await page.evaluate("""
                    () => {
                        const body = document.body;
                        if (!body) return '';

                        // 移除无关元素
                        const clone = body.cloneNode(true);
                        const remove = clone.querySelectorAll('script, style, nav, header, footer, iframe, .chapter-control, .comment');
                        remove.forEach(el => el.remove());

                        const text = clone.innerText || '';
                        const lines = text.split('\\n').filter(l => l.trim().length > 0);
                        return lines.join('\\n');
                    }
                """)

            # 清理文本
            content = content.strip()
            if content:
                content = content.replace("　", "  ")  # 全角空格
                content = content.replace("\r", "")

            return content

        except Exception as e:
            logger.debug("章节内容提取异常: {} - {}", chapter.title[:20], e)
            return ""
