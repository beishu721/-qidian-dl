import asyncio
import random
from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from ..config import settings


STEALTH_SCRIPT = """
// 1. 隐藏 webdriver 属性
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 2. 伪造 plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        plugins.item = (i) => plugins[i] || null;
        plugins.namedItem = (name) => plugins.find(p => p.name === name) || null;
        plugins.refresh = () => {};
        Object.setPrototypeOf(plugins, PluginArray.prototype);
        return plugins;
    }
});

// 3. 伪造 languages
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });

// 4. 伪造 platform
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

// 5. 伪造 hardwareConcurrency
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

// 6. 伪造 chrome.runtime (Playwright Chromium 默认没有)
window.chrome = {
    ...window.chrome,
    runtime: {
        ...(window.chrome?.runtime || {}),
        PlatformOs: 'win',
        PlatformArch: 'x86-64',
        PlatformNaclArch: 'x86-64',
        connect: () => {},
        sendMessage: () => {},
        onMessage: { addListener: () => {}, removeListener: () => {} },
        onConnect: { addListener: () => {}, removeListener: () => {} },
    },
    loadTimes: () => ({
        requestTime: Date.now() / 1000 - 0.5,
        startLoadTime: Date.now() / 1000 - 0.4,
        commitLoadTime: Date.now() / 1000 - 0.2,
        finishDocumentLoadTime: Date.now() / 1000 - 0.1,
        finishLoadTime: Date.now() / 1000,
        firstPaintTime: Date.now() / 1000 - 0.3,
        navigationType: 'Other',
        wasFetchedViaSpdy: false,
        connectionInfo: 'http/1.1',
    }),
    csi: () => ({
        startE: Date.now() - 400,
        onloadT: Date.now() - 50,
        pageT: 350,
        tran: 15,
    }),
};

// 7. 伪造权限
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission, onchange: null })
        : originalQuery(parameters)
);

// 8. 覆盖 WebGL 指纹
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel(R) UHD Graphics';
    return getParameter.call(this, parameter);
};
"""


class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser: Browser | None = None
        self.contexts: list[BrowserContext] = []

    async def start(self):
        self.playwright = await async_playwright().start()
        cfg = settings.browser
        self.browser = await self.playwright.chromium.launch(
            channel="chrome",
            headless=cfg.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                f"--window-size={cfg.viewport_width},{cfg.viewport_height}",
            ],
        )
        logger.info("浏览器已启动 (headless={})", cfg.headless)

    async def create_context(self) -> BrowserContext:
        cfg = settings.browser
        context = await self.browser.new_context(
            viewport={"width": cfg.viewport_width, "height": cfg.viewport_height},
            locale=cfg.locale,
            timezone_id=cfg.timezone_id,
        )
        await context.add_init_script(STEALTH_SCRIPT)
        self.contexts.append(context)
        return context

    async def new_page(self) -> Page:
        context = await self.create_context()
        page = await context.new_page()
        return page

    async def navigate_safe(self, url: str, retries: int = 3) -> Page:
        """导航到URL，自动处理WAF挑战，带重试"""
        for attempt in range(retries):
            page = await self.new_page()
            try:
                logger.debug("导航: {} (第{}次)", url, attempt + 1)
                # 用 networkidle 等页面JS渲染完，避免SPA还在加载就操作
                await page.goto(url, wait_until="networkidle", timeout=45000)

                # 额外等几秒确保WAF的probe.js执行完毕
                await asyncio.sleep(random.uniform(1.5, 3))

                # 检测是否被WAF拦截（检查标题是否还是WAF挑战页）
                try:
                    title = await page.title()
                    if "安全验证" in title or "Access Denied" in title:
                        logger.warning("WAF拦截，等待手动处理...")
                        await page.pause()
                except Exception:
                    pass  # 页面偶尔仍在加载，忽略此检查

                # 模拟人类行为
                await self._human_behavior(page)

                return page
            except Exception as e:
                logger.error("导航失败 (尝试 {}/{}): {}", attempt + 1, retries, e)
                await page.close()
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt * 2)

        raise RuntimeError(f"无法导航到 {url}")

    async def _human_behavior(self, page: Page):
        """模拟人类操作：随机滚动、鼠标移动"""
        try:
            viewport = page.viewport_size
            if viewport:
                w, h = viewport["width"], viewport["height"]
                # 随机滚动
                scroll_y = random.randint(100, min(800, h * 3))
                await page.mouse.move(
                    random.randint(w // 4, 3 * w // 4),
                    random.randint(50, h - 100),
                )
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await page.evaluate(f"window.scrollTo({{top: {scroll_y}, behavior: 'smooth'}})")
                await asyncio.sleep(random.uniform(0.5, 1.2))
        except Exception:
            pass  # 模拟行为失败不应影响主流程

    async def extract_text_content(self, page: Page, selector: str) -> str:
        """从DOM提取文本内容"""
        try:
            await page.wait_for_selector(selector, timeout=10000)
            text = await page.eval_on_selector(selector, "el => el.innerText")
            return text.strip()
        except Exception:
            return ""

    async def close(self):
        for ctx in self.contexts:
            await ctx.close()
        self.contexts.clear()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("浏览器已关闭")
