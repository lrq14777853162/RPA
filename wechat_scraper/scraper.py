"""
RPA 模式微信公众号文章爬虫。

工作流程：
  1. 打开微信 Web（wx.qq.com），检测是否已有有效 session
  2. 若无 session，保存二维码图片并提示用户扫码登录
  3. 登录后，通过搜索栏搜索关键词，切换到"文章"标签
  4. 提取文章元数据（标题、链接、公众号、时间）
  5. 逐篇访问文章页（mp.weixin.qq.com）抓取正文
  6. 保存 session 以便下次免登录
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PwTimeout,
)
from rich.console import Console
from rich.panel import Panel

from .models import Article
from .utils import async_random_delay, parse_publish_time, clean_text, count_chinese_words

console = Console()

# 微信 Web 入口
WECHAT_WEB_URL = "https://wx.qq.com"

# 登录成功后的聊天列表标志选择器（多个备用，任意一个出现即视为登录成功）
_LOGIN_SUCCESS_SELECTORS = [
    "#chatArea",
    ".chat_list",
    "div.chat-list",
    "#navBar",
    ".main-panel",
    "mm-panel",
]

# 搜索框选择器（备用列表）
_SEARCH_BOX_SELECTORS = [
    "input.search_input",
    "#search_bar input",
    "input[placeholder*='搜索']",
    "input[placeholder*='Search']",
    ".search-bar input",
]

# 二维码图片选择器（备用列表）
_QR_IMG_SELECTORS = [
    "img.qrcode",
    "#qrcode img",
    ".qrcode img",
    "img[src*='qrcode']",
    "img[src*='webwxgetqrcode']",
    ".login_qrcode img",
    "img.img_qr",
]

# 常见 User-Agent 池
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


class WechatScraper:
    """
    RPA 模式公众号文章爬虫。

    使用 Playwright 直接操控微信 Web（wx.qq.com），
    模拟人工登录、搜索、翻页、阅读，全程 RPA 驱动。

    参数
    ----
    keyword : str
        搜索关键词
    max_pages : int
        最多翻页次数（每页约 10 条文章结果）
    fetch_content : bool
        是否进入文章页面抓取正文
    headless : bool
        是否无头模式；首次登录必须设为 False 以便扫码
    browser_type : str
        "chromium" / "firefox" / "webkit"
    delay_min / delay_max : float
        操作间随机延迟区间（秒），模拟人工节奏
    timeout : int
        页面及元素等待超时（毫秒）
    viewport : tuple[int, int]
        浏览器窗口尺寸
    session_dir : str | Path | None
        session 保存目录；若指定则自动保存/复用登录状态
    qr_save_path : str | Path | None
        二维码保存路径（默认 output/qrcode.png）
    """

    def __init__(
        self,
        keyword: str,
        *,
        max_pages: int = 5,
        fetch_content: bool = True,
        headless: bool = False,
        browser_type: str = "chromium",
        delay_min: float = 1.5,
        delay_max: float = 3.5,
        timeout: int = 30_000,
        viewport: tuple[int, int] = (1280, 800),
        session_dir: str | Path | None = None,
        qr_save_path: str | Path | None = None,
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
        self.session_dir = Path(session_dir) if session_dir else None
        self.qr_save_path = Path(qr_save_path) if qr_save_path else Path("output/qrcode.png")

        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ── 生命周期 ─────────────────────────────────────────────────

    async def __aenter__(self) -> "WechatScraper":
        await self._init_browser()
        return self

    async def __aexit__(self, *_) -> None:
        await self._close_browser()

    @property
    def _session_file(self) -> Path | None:
        if self.session_dir:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            return self.session_dir / "session.json"
        return None

    async def _init_browser(self) -> None:
        self._pw = await async_playwright().start()
        launcher = getattr(self._pw, self.browser_type)
        self._browser = await launcher.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        user_agent = random.choice(_USER_AGENTS)
        ctx_kwargs: dict = dict(
            user_agent=user_agent,
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        # 尝试加载已保存的 session
        if self._session_file and self._session_file.exists():
            try:
                ctx_kwargs["storage_state"] = str(self._session_file)
                console.print(f"[dim]已加载已保存 session：{self._session_file}[/dim]")
            except Exception:
                pass

        self._context = await self._browser.new_context(**ctx_kwargs)
        # 隐藏自动化特征
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    async def _close_browser(self) -> None:
        # 保存 session（登录态）
        if self._context and self._session_file:
            try:
                state = await self._context.storage_state()
                self._session_file.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                console.print(f"[dim]Session 已保存：{self._session_file}[/dim]")
            except Exception as exc:
                console.print(f"[yellow]保存 session 失败：{exc}[/yellow]")

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

    # ── 主入口 ───────────────────────────────────────────────────

    async def scrape(self) -> list[Article]:
        """完整 RPA 流程：登录 → 搜索 → 抓取，返回文章列表。"""
        articles: list[Article] = []
        async for article in self._iter_articles():
            articles.append(article)
        return articles

    async def _iter_articles(self) -> AsyncIterator[Article]:
        main_page = await self._new_page()
        try:
            # ① RPA 步骤一：登录
            await self._rpa_login(main_page)

            # ② RPA 步骤二：搜索关键词
            await self._rpa_search(main_page, self.keyword)

            # ③ RPA 步骤三：逐页采集文章
            collected = 0
            for page_num in range(1, self.max_pages + 1):
                console.print(
                    f"[bold cyan]>> 第 {page_num} 页[/bold cyan]  关键词: [yellow]{self.keyword}[/yellow]"
                )
                stubs = await self._rpa_collect_page(main_page, page_num)
                if not stubs:
                    console.print("[dim]  已无更多文章结果，停止翻页。[/dim]")
                    break

                console.print(f"  [green]本页获取 {len(stubs)} 篇文章[/green]")
                for stub in stubs:
                    if self.fetch_content:
                        await self._enrich_with_content(stub)
                    yield stub
                    collected += 1
                    await async_random_delay(self.delay_min, self.delay_max)

                # 翻页
                if page_num < self.max_pages:
                    has_next = await self._rpa_next_page(main_page)
                    if not has_next:
                        break
                    await async_random_delay(self.delay_min, self.delay_max)
        finally:
            await main_page.close()

    # ── RPA 步骤一：登录 ─────────────────────────────────────────

    async def _rpa_login(self, page: Page) -> None:
        """导航到微信 Web，检测登录状态；若未登录则等待用户扫码。"""
        console.print("[bold]→ [RPA] 打开微信 Web……[/bold]")
        try:
            await page.goto(WECHAT_WEB_URL, wait_until="domcontentloaded")
        except PwTimeout:
            console.print("[yellow]  页面加载较慢，继续等待……[/yellow]")

        # 快速检测：是否已经登录
        if await self._is_logged_in(page, timeout=5_000):
            console.print("[green]  已检测到有效登录状态，跳过扫码。[/green]")
            return

        # 未登录：提取二维码，提示扫码
        console.print("[yellow]  未检测到登录状态，正在提取二维码……[/yellow]")
        await self._show_qr_code(page)

        # 等待用户扫码并确认（最多等待 3 分钟）
        console.print("[bold yellow]  请用微信扫描上方二维码，扫码后在手机上点击「登录」……[/bold yellow]")
        logged_in = await self._is_logged_in(page, timeout=180_000)
        if not logged_in:
            raise RuntimeError("等待扫码超时（3 分钟），请重新运行程序。")
        console.print("[bold green]  ✓ 登录成功！[/bold green]")
        await async_random_delay(1.5, 2.5)

    async def _is_logged_in(self, page: Page, timeout: int = 5_000) -> bool:
        """检测聊天列表是否出现（即已登录）。"""
        for sel in _LOGIN_SUCCESS_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=timeout)
                return True
            except PwTimeout:
                continue
        return False

    async def _show_qr_code(self, page: Page) -> None:
        """找到登录二维码图片，保存为文件并在控制台提示。"""
        qr_el = None
        for sel in _QR_IMG_SELECTORS:
            try:
                qr_el = await page.wait_for_selector(sel, timeout=8_000)
                if qr_el:
                    break
            except PwTimeout:
                continue

        self.qr_save_path.parent.mkdir(parents=True, exist_ok=True)

        if qr_el:
            # 截图二维码区域
            try:
                await qr_el.screenshot(path=str(self.qr_save_path))
                console.print(
                    Panel(
                        f"[bold yellow]二维码已保存到：[white]{self.qr_save_path}[/white]\n"
                        "请用微信扫描该图片文件中的二维码完成登录。[/bold yellow]",
                        title="📱 扫码登录",
                        border_style="yellow",
                    )
                )
                return
            except Exception:
                pass

        # 如果无法截图到单个元素，截取整个页面
        full_path = self.qr_save_path.parent / "login_page.png"
        try:
            await page.screenshot(path=str(full_path))
            console.print(
                Panel(
                    f"[bold yellow]登录页截图已保存到：[white]{full_path}[/white]\n"
                    "请查看截图，找到二维码后用微信扫描。[/bold yellow]",
                    title="📱 扫码登录",
                    border_style="yellow",
                )
            )
        except Exception as exc:
            console.print(f"[red]  无法保存二维码截图：{exc}[/red]")
            console.print("[yellow]  请查看浏览器窗口中的二维码并用微信扫描。[/yellow]")

    # ── RPA 步骤二：搜索 ─────────────────────────────────────────

    async def _rpa_search(self, page: Page, keyword: str) -> None:
        """在微信 Web 搜索栏中输入关键词，切换到文章结果标签。"""
        console.print(f"[bold]→ [RPA] 搜索关键词：[yellow]{keyword}[/yellow][/bold]")

        # 找到搜索框
        search_box = None
        for sel in _SEARCH_BOX_SELECTORS:
            try:
                search_box = await page.wait_for_selector(sel, timeout=8_000)
                if search_box:
                    break
            except PwTimeout:
                continue

        if not search_box:
            # 尝试点击搜索图标（有些界面搜索框默认隐藏）
            try:
                icon = await page.query_selector(
                    ".icon-search, .search-btn, [aria-label*='搜索'], [title*='搜索']"
                )
                if icon:
                    await icon.click()
                    await async_random_delay(0.5, 1.0)
                    for sel in _SEARCH_BOX_SELECTORS:
                        try:
                            search_box = await page.wait_for_selector(sel, timeout=4_000)
                            if search_box:
                                break
                        except PwTimeout:
                            continue
            except Exception:
                pass

        if not search_box:
            raise RuntimeError("未找到搜索框，请检查微信 Web 界面是否正常加载。")

        await search_box.click()
        await async_random_delay(0.3, 0.8)
        # 清空并输入关键词（模拟逐字输入，更像人工操作）
        await search_box.fill("")
        await search_box.type(keyword, delay=80)
        await page.keyboard.press("Enter")
        await async_random_delay(1.5, 2.5)

        # 尝试切换到"文章"标签（如果存在多标签界面）
        await self._switch_to_article_tab(page)

    async def _switch_to_article_tab(self, page: Page) -> None:
        """在搜索结果中切换到「公众号文章」标签。"""
        article_tab_selectors = [
            "//span[contains(text(),'文章')]",
            "//a[contains(text(),'文章')]",
            "//div[contains(@class,'tab') and contains(text(),'文章')]",
            "[data-tab='article']",
            ".tab-item:has-text('文章')",
        ]
        for sel in article_tab_selectors:
            try:
                if sel.startswith("//"):
                    tab = await page.wait_for_selector(f"xpath={sel}", timeout=4_000)
                else:
                    tab = await page.wait_for_selector(sel, timeout=4_000)
                if tab:
                    await tab.click()
                    await async_random_delay(1.0, 2.0)
                    console.print("[dim]  已切换到「文章」标签。[/dim]")
                    return
            except PwTimeout:
                continue
        console.print("[dim]  未找到文章标签，使用当前搜索结果。[/dim]")

    # ── RPA 步骤三：采集当前页文章 ───────────────────────────────

    async def _rpa_collect_page(self, page: Page, page_num: int) -> list[Article]:
        """从当前搜索结果页面提取文章列表。"""
        await async_random_delay(1.0, 2.0)

        # 文章条目候选选择器（微信 Web 不同版本 DOM 差异较大）
        item_selectors = [
            ".search_result .media_default",   # 常见文章卡片
            ".search-item[data-type='article']",
            ".search_result_item",
            ".article-item",
            "li.media_default",
        ]

        items = []
        for sel in item_selectors:
            items = await page.query_selector_all(sel)
            if items:
                break

        if not items:
            # 最后兜底：尝试通用 li 条目中含标题链接的
            items = await page.query_selector_all("li:has(a[href*='mp.weixin.qq.com'])")

        if not items:
            console.print("[dim]  当前页面未找到文章条目。[/dim]")
            return []

        articles: list[Article] = []
        for item in items:
            try:
                article = await self._parse_result_item(item, page_num)
                if article:
                    articles.append(article)
            except Exception as exc:
                console.print(f"  [yellow]解析条目时出错: {exc}[/yellow]")

        return articles

    async def _parse_result_item(self, item, page_num: int) -> Article | None:
        """从单个搜索结果条目中提取文章元数据。"""
        # 标题 & 链接（优先 mp.weixin.qq.com 链接）
        link_el = await item.query_selector("a[href*='mp.weixin.qq.com']")
        if not link_el:
            link_el = await item.query_selector("h4 a, h3 a, .title a, a.title")
        if not link_el:
            return None

        href = await link_el.get_attribute("href") or ""
        if not href:
            return None

        # 标题文字
        title_el = await item.query_selector("h4, h3, .title, .media_title")
        title = clean_text(await title_el.inner_text()) if title_el else clean_text(await link_el.inner_text())
        if not title:
            return None

        # 摘要
        summary = ""
        desc_el = await item.query_selector(".desc, .summary, p, .media_desc")
        if desc_el:
            summary = clean_text(await desc_el.inner_text())

        # 公众号名称
        account_name = ""
        account_el = await item.query_selector(
            ".account, .source, .nickname, .media_source, span.nikename"
        )
        if account_el:
            account_name = clean_text(await account_el.inner_text())

        # 发布时间
        time_raw = ""
        time_el = await item.query_selector(".time, .date, .publish_time, em, label")
        if time_el:
            time_raw = clean_text(await time_el.inner_text())
        publish_time = parse_publish_time(time_raw) if time_raw else None

        # 封面图
        cover = ""
        img_el = await item.query_selector("img")
        if img_el:
            cover = (
                await img_el.get_attribute("src")
                or await img_el.get_attribute("data-src")
                or ""
            )

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

    async def _rpa_next_page(self, page: Page) -> bool:
        """
        翻到下一页文章结果。
        返回 True 表示成功翻页，False 表示无下一页。
        """
        # 方式一：点击「下一页」按钮
        next_selectors = [
            "//button[contains(text(),'下一页')]",
            "//a[contains(text(),'下一页')]",
            ".page-next",
            "a.next",
            "[aria-label='下一页']",
        ]
        for sel in next_selectors:
            try:
                if sel.startswith("//"):
                    btn = await page.query_selector(f"xpath={sel}")
                else:
                    btn = await page.query_selector(sel)
                if btn and await btn.is_enabled():
                    await btn.click()
                    await async_random_delay(1.5, 2.5)
                    return True
            except Exception:
                continue

        # 方式二：滚动到底部触发加载更多
        prev_height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await async_random_delay(2.0, 3.0)
        new_height = await page.evaluate("document.body.scrollHeight")
        return new_height > prev_height

    # ── 文章正文抓取（访问 mp.weixin.qq.com）───────────────────

    async def _enrich_with_content(self, article: Article) -> None:
        """新开标签页访问文章原始链接，抓取正文后关闭。"""
        if not article.url:
            return

        content_page = await self._new_page()
        try:
            console.print(f"  [dim]→ 抓取正文: {article.title[:40]}…[/dim]")
            try:
                await content_page.goto(article.url, wait_until="domcontentloaded")
            except PwTimeout:
                console.print("  [yellow]  文章页加载超时，跳过正文。[/yellow]")
                return

            # 更新真实 URL（可能经过跳转）
            article.url = content_page.url

            try:
                await content_page.wait_for_selector(
                    "#js_content, .rich_media_content", timeout=10_000
                )
            except PwTimeout:
                pass

            await self._extract_content(content_page, article)

        except Exception as exc:
            console.print(f"  [yellow]  抓取正文时出错: {exc}[/yellow]")
        finally:
            await content_page.close()

    async def _extract_content(self, page: Page, article: Article) -> None:
        """从微信文章页面提取正文、图片等信息。"""
        content_el = await page.query_selector("#js_content, .rich_media_content")
        if content_el:
            article.content_html = await content_el.inner_html()
            article.content = clean_text(await content_el.inner_text())
            article.word_count = count_chinese_words(article.content)

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
