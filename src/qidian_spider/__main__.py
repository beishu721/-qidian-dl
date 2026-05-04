import asyncio
import click

from .browser.manager import BrowserManager
from .storage.database import Database
from .spiders.book_spider import BookSpider
from .config import settings
from .utils.logger import logger


@click.group()
def cli():
    """起点中文网书籍爬虫工具"""


@cli.command()
@click.argument("book_id", type=int)
@click.option("--headless/--no-headless", default=True, help="无头模式")
@click.option("--chapters-only", is_flag=True, help="仅爬取章节（跳过已有书籍信息）")
def book(book_id: int, headless: bool, chapters_only: bool):
    """爬取单本书籍 (按 book_id)"""
    settings.browser.headless = headless
    asyncio.run(_scrape_book(book_id, chapters_only))


async def _scrape_book(book_id: int, chapters_only: bool):
    db = Database(settings.storage.db_path)
    await db.connect()

    browser = BrowserManager()
    await browser.start()

    try:
        spider = BookSpider(browser, db)
        await spider.scrape(book_id)
    except Exception as e:
        logger.exception("爬取失败: {}", e)
    finally:
        await browser.close()
        await db.close()


@cli.command()
@click.argument("book_ids", nargs=-1, type=int)
@click.option("--headless/--no-headless", default=True, help="无头模式")
@click.option("--delay", type=float, default=30.0, help="书籍之间的延迟(秒)")
def batch(book_ids: tuple[int, ...], headless: bool, delay: float):
    """批量爬取多本书籍"""
    settings.browser.headless = headless
    asyncio.run(_scrape_batch(list(book_ids), delay))


async def _scrape_batch(book_ids: list[int], delay: float):
    db = Database(settings.storage.db_path)
    await db.connect()

    browser = BrowserManager()
    await browser.start()

    spider = BookSpider(browser, db)
    success = 0

    try:
        for i, bid in enumerate(book_ids, 1):
            logger.info("批量爬取 [{}/{}] ID={}", i, len(book_ids), bid)
            try:
                await spider.scrape(bid)
                success += 1
            except Exception as e:
                logger.error("ID {} 爬取失败: {}", bid, e)

            if i < len(book_ids):
                logger.info("等待 {} 秒后爬取下一本...", delay)
                await asyncio.sleep(delay)
    finally:
        await browser.close()
        await db.close()

    logger.info("批量爬取完成: {}/{} 成功", success, len(book_ids))


@cli.command()
@click.option("--headless/--no-headless", default=True)
def test(headless: bool):
    """测试浏览器WAF绕过能力"""
    settings.browser.headless = headless
    asyncio.run(_test_browser())


async def _test_browser():
    browser = BrowserManager()
    await browser.start()

    try:
        logger.info("测试访问起点首页...")
        page = await browser.navigate_safe("https://www.qidian.com/")
        title = await page.title()
        logger.success("成功! 页面标题: {}", title)

        await asyncio.sleep(2)
        await page.close()
    except Exception as e:
        logger.error("测试失败: {}", e)
    finally:
        await browser.close()


if __name__ == "__main__":
    cli()
