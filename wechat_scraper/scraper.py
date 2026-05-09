"""Core scraper: search WeChat articles via Sogou and extract content."""

from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator
from urllib.parse import urlencode, urlparse, parse_qs

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PwTimeout,
)
from rich.console import Console

from .models import Article
from .utils import async_random_delay, parse_publish_time, clean_text, count_chinese_words

console = Console()

# 搜狗微信搜索地址
SOGOU_WEIXIN_URL = "https://weixin.sogou.com/weixin"

# 常见 User-Agent 池
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
]

import random  # noqa: E402


class WechatScraper:
    """
    公众号文章爬虫。

    使用搜狗微信搜索（https://weixin.sogou.com）作为入口，
    只抓取公开可访问的文章，无需微信账号登录。

    参数
    ----
    keyword : str
        搜索关键词
    max_pages : int
        最多爬取页数（搜狗搜索结果）
    fetch_content : bool
        是否进入文章页面抓取正文
    headless : bool
        是否无头模式运行浏览器
    browser_type : str
        "chromium" / "firefox" / "webkit"
    delay_min / delay_max : float
        请求间随机延迟区间（秒）
    timeout : int
        页面加载超时（毫秒）
    viewport : tuple[int, int]
        浏览器窗口尺寸
    """

    def __init__(
        self,
        keyword: str,
        *,
        max_pages: int = 5,
        fetch_content: bool = True,
        headless: bool = True,
        browser_type: str = "chromium",
        delay_min: float = 2.0,
        delay_max: float = 5.0,
        timeout: int = 30_000,
        viewport: tuple[int, int] = (1280, 800),
    ) -> None:
        self.keyword = keyword
        self.max_pages = max_pages
        self.fetch_content = fetch_content
        self.headless = headless
        self.browser_type = browser_type
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = timeout
        self.viewport = viewport

        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ── 生命周期 ─────────────────────────────────────────────────

    async def __aenter__(self) -> "WechatScraper":
        await self._init_browser()
        return self

    async def __aexit__(self, *_) -> None:
        await self._close_browser()

    async def _init_browser(self) -> None:
        self._pw = await async_playwright().start()
        launcher = getattr(self._pw, self.browser_type)
        self._browser = await launcher.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        user_agent = random.choice(_USER_AGENTS)
        self._context = await self._browser.new_context(
            user_agent=user_agent,
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        # 隐藏 Playwright 自动化特征
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    async def _close_browser(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw"):
            await self._pw.stop()

    async def _new_page(self) -> Page:
        page = await self._context.new_page()
        page.set_default_timeout(self.timeout)
        return page

    # ── 主要爬取流程 ─────────────────────────────────────────────

    async def scrape(self) -> list[Article]:
        """爬取关键词相关文章，返回 Article 列表。"""
        articles: list[Article] = []
        async for article in self._iter_articles():
            articles.append(article)
        return articles

    async def _iter_articles(self) -> AsyncIterator[Article]:
        """逐页爬取，每篇文章以生成器形式返回。"""
        page = await self._new_page()
        try:
            for page_num in range(1, self.max_pages + 1):
                console.print(
                    f"[bold cyan]>> 搜索第 {page_num} 页[/bold cyan]  关键词: [yellow]{self.keyword}[/yellow]"
                )
                items = await self._fetch_search_page(page, page_num)
                if not items:
                    console.print("[dim]  已无更多结果，停止翻页。[/dim]")
                    break

                for stub in items:
                    if self.fetch_content:
                        await self._enrich_with_content(stub)
                    yield stub
                    await async_random_delay(self.delay_min, self.delay_max)

                if page_num < self.max_pages:
                    await async_random_delay(self.delay_min, self.delay_max)
        finally:
            await page.close()

    # ── 搜索结果页解析 ───────────────────────────────────────────

    async def _fetch_search_page(self, page: Page, page_num: int) -> list[Article]:
        """请求搜狗微信搜索结果页并解析文章列表。"""
        params = {
            "type": "2",       # type=2 表示文章搜索
            "query": self.keyword,
            "page": page_num,
        }
        url = f"{SOGOU_WEIXIN_URL}?{urlencode(params)}"

        try:
            await page.goto(url, wait_until="domcontentloaded")
        except PwTimeout:
            console.print(f"[red]  页面加载超时: {url}[/red]")
            return []

        # 检测验证码 / 风控页面
        if await self._is_blocked(page):
            console.print("[red bold]  检测到验证码或风控页面，暂停30秒后重试……[/red bold]")
            await asyncio.sleep(30)
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except PwTimeout:
                return []
            if await self._is_blocked(page):
                console.print("[red]  仍被拦截，跳过本页。[/red]")
                return []

        articles = await self._parse_search_results(page, page_num)
        console.print(f"  [green]本页获取 {len(articles)} 篇文章[/green]")
        return articles

    async def _is_blocked(self, page: Page) -> bool:
        """判断是否遭遇验证码或风控。"""
        title = await page.title()
        blocked_keywords = ["验证", "captcha", "blocked", "人机验证"]
        for kw in blocked_keywords:
            if kw.lower() in title.lower():
                return True
        # 检查页面是否包含滑块/验证码元素
        if await page.query_selector(".tc-captcha-container, #verify-bar-icon, .sgs-captcha"):
            return True
        return False

    async def _parse_search_results(self, page: Page, page_num: int) -> list[Article]:
        """解析搜狗微信搜索结果页中的文章列表。"""
        articles: list[Article] = []

        # 搜狗文章条目选择器
        items = await page.query_selector_all(".news-box .news-list li")
        if not items:
            # 备用选择器
            items = await page.query_selector_all("ul.news-list > li")

        for item in items:
            try:
                article = await self._parse_search_item(item, page_num)
                if article:
                    articles.append(article)
            except Exception as exc:
                console.print(f"  [yellow]解析条目时出错: {exc}[/yellow]")

        return articles

    async def _parse_search_item(self, item, page_num: int) -> Article | None:
        """从单个搜索结果条目中提取元数据。"""
        # 标题 & URL
        title_el = await item.query_selector("h3 a, .txt-box h3 a")
        if not title_el:
            return None

        title = clean_text(await title_el.inner_text())
        href = await title_el.get_attribute("href") or ""
        # 有些链接是相对路径
        if href.startswith("/"):
            href = "https://weixin.sogou.com" + href

        # 摘要
        summary = ""
        summary_el = await item.query_selector(".txt-box p, p.txt-info")
        if summary_el:
            summary = clean_text(await summary_el.inner_text())

        # 公众号名称
        account_name = ""
        account_el = await item.query_selector(
            ".account, .s-p, span.account, .js_name, a.account"
        )
        if account_el:
            account_name = clean_text(await account_el.inner_text())

        # 发布时间
        time_raw = ""
        time_el = await item.query_selector("label, .s-p span, .news-from .s-p")
        if time_el:
            time_raw = clean_text(await time_el.inner_text())
        publish_time = parse_publish_time(time_raw) if time_raw else None

        # 封面图
        cover = ""
        img_el = await item.query_selector("img")
        if img_el:
            cover = await img_el.get_attribute("src") or await img_el.get_attribute("data-src") or ""

        return Article(
            title=title,
            url=href,
            account_name=account_name,
            summary=summary,
            publish_time=publish_time,
            publish_time_raw=time_raw,
            cover_image=cover,
            keyword=self.keyword,
            page_num=page_num,
        )

    # ── 文章正文抓取 ──────────────────────────────────────────────

    async def _enrich_with_content(self, article: Article) -> None:
        """访问文章页面，抓取正文内容并填充到 article 对象。"""
        if not article.url:
            return

        content_page = await self._new_page()
        try:
            console.print(f"  [dim]抓取正文: {article.title[:40]}…[/dim]")
            try:
                await content_page.goto(article.url, wait_until="domcontentloaded")
            except PwTimeout:
                console.print(f"  [yellow]  文章页加载超时，跳过正文。[/yellow]")
                return

            # 搜狗搜索结果 URL 可能是中转页，等待跳转到真实微信文章页
            # 真实微信文章域名：mp.weixin.qq.com
            try:
                await content_page.wait_for_url("**/mp.weixin.qq.com/**", timeout=10_000)
            except PwTimeout:
                pass  # 可能已经是微信文章页，继续

            final_url = content_page.url
            article.url = final_url  # 更新为真实文章 URL

            # 等待文章主体加载
            try:
                await content_page.wait_for_selector("#js_content, .rich_media_content", timeout=10_000)
            except PwTimeout:
                pass

            await self._extract_content(content_page, article)

        except Exception as exc:
            console.print(f"  [yellow]  抓取正文时出错: {exc}[/yellow]")
        finally:
            await content_page.close()

    async def _extract_content(self, page: Page, article: Article) -> None:
        """从微信文章页面提取正文、图片等信息。"""
        # 正文 HTML
        content_el = await page.query_selector("#js_content, .rich_media_content")
        if content_el:
            article.content_html = await content_el.inner_html()
            article.content = clean_text(await content_el.inner_text())
            article.word_count = count_chinese_words(article.content)

            # 提取图片
            imgs = await content_el.query_selector_all("img")
            for img in imgs:
                src = (
                    await img.get_attribute("data-src")
                    or await img.get_attribute("src")
                    or ""
                )
                if src and src not in article.images:
                    article.images.append(src)

        # 公众号名称（文章页更准确）
        if not article.account_name:
            name_el = await page.query_selector(
                "#js_name, .profile_nickname, .rich_media_meta_nickname"
            )
            if name_el:
                article.account_name = clean_text(await name_el.inner_text())

        # 发布时间（文章页更准确）
        if not article.publish_time:
            time_el = await page.query_selector(
                "#publish_time, em#publish_time, .rich_media_meta_text"
            )
            if time_el:
                raw = clean_text(await time_el.inner_text())
                article.publish_time_raw = raw
                article.publish_time = parse_publish_time(raw)
