"""CLI entry point for the WeChat article scraper (RPA mode)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click
import yaml
from rich.console import Console
from rich.table import Table

from wechat_scraper.scraper import WechatScraper
from wechat_scraper.storage import save_articles

console = Console()

DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def _load_config(config_path: Path) -> dict:
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@click.command()
@click.argument("keyword")
@click.option(
    "--pages", "-p",
    default=None,
    type=int,
    help="最多采集页数（覆盖 config.yaml 中的 max_pages）",
)
@click.option(
    "--output-dir", "-o",
    default=None,
    type=click.Path(),
    help="输出目录（覆盖 config.yaml 中的 output_dir）",
)
@click.option(
    "--format", "-f",
    "fmt",
    default=None,
    multiple=True,
    type=click.Choice(["json", "csv", "sqlite"], case_sensitive=False),
    help="输出格式，可多选（覆盖 config.yaml）",
)
@click.option(
    "--no-content",
    is_flag=True,
    default=False,
    help="不抓取文章正文，只保存搜索结果元数据",
)
@click.option(
    "--headless",
    is_flag=True,
    default=False,
    help="无头模式（需已有有效 session，否则无法完成扫码登录）",
)
@click.option(
    "--session-dir", "-s",
    default=None,
    type=click.Path(),
    help="Session 目录，保存/复用登录状态（覆盖 config.yaml）",
)
@click.option(
    "--config", "-c",
    "config_path",
    default=str(DEFAULT_CONFIG),
    type=click.Path(exists=False),
    show_default=True,
    help="配置文件路径",
)
def main(
    keyword: str,
    pages: Optional[int],
    output_dir: Optional[str],
    fmt: tuple[str, ...],
    no_content: bool,
    headless: bool,
    session_dir: Optional[str],
    config_path: str,
) -> None:
    """
    公众号文章爬虫（RPA 模式）— 操控微信 Web 扫码登录后按关键词搜索文章。

    \b
    首次使用（需扫码）：
        python main.py 人工智能

    Session 已保存后（免扫码）：
        python main.py 人工智能 --headless --session-dir .session

    \b
    更多示例：
        python main.py 人工智能 --pages 3 --format json --format csv
        python main.py 人工智能 --no-content
    """
    cfg = _load_config(Path(config_path))
    scraper_cfg = cfg.get("scraper", {})
    storage_cfg = cfg.get("storage", {})

    # 参数优先级：命令行 > config.yaml > 默认值
    max_pages = pages if pages is not None else scraper_cfg.get("max_pages", 5)
    out_dir = output_dir or storage_cfg.get("output_dir", "output")
    formats = list(fmt) if fmt else storage_cfg.get("formats", ["json", "csv"])
    fetch_content = not no_content and scraper_cfg.get("fetch_content", True)
    # headless：命令行 --headless 优先；否则读 config；默认 False（须可见才能扫码）
    use_headless = headless or scraper_cfg.get("headless", False)
    sess_dir = session_dir or scraper_cfg.get("session_dir") or None

    console.rule("[bold]微信公众号文章爬虫（RPA 模式）[/bold]")
    console.print(f"关键词  : [yellow]{keyword}[/yellow]")
    console.print(f"最大页数: {max_pages}")
    console.print(f"抓取正文: {'是' if fetch_content else '否'}")
    console.print(f"输出格式: {', '.join(formats)}")
    console.print(f"输出目录: {out_dir}")
    console.print(f"Session : {sess_dir or '（不保存）'}")
    console.print(f"无头模式: {'是' if use_headless else '否（浏览器可见，可扫码）'}")
    console.rule()

    asyncio.run(
        _run(
            keyword=keyword,
            max_pages=max_pages,
            fetch_content=fetch_content,
            headless=use_headless,
            out_dir=out_dir,
            formats=formats,
            session_dir=sess_dir,
            scraper_cfg=scraper_cfg,
        )
    )


async def _run(
    keyword: str,
    max_pages: int,
    fetch_content: bool,
    headless: bool,
    out_dir: str,
    formats: list[str],
    session_dir: Optional[str],
    scraper_cfg: dict,
) -> None:
    async with WechatScraper(
        keyword=keyword,
        max_pages=max_pages,
        fetch_content=fetch_content,
        headless=headless,
        browser_type=scraper_cfg.get("browser", "chromium"),
        delay_min=scraper_cfg.get("delay_min", 1.5),
        delay_max=scraper_cfg.get("delay_max", 3.5),
        timeout=scraper_cfg.get("timeout", 30_000),
        viewport=(
            scraper_cfg.get("viewport_width", 1280),
            scraper_cfg.get("viewport_height", 800),
        ),
        session_dir=session_dir,
        qr_save_path=Path(out_dir) / "qrcode.png",
    ) as scraper:
        articles = await scraper.scrape()

    if not articles:
        console.print("[bold red]未抓取到任何文章，请检查关键词或登录状态。[/bold red]")
        return

    # 打印摘要表格
    table = Table(title=f"抓取结果（共 {len(articles)} 篇）", show_lines=True)
    table.add_column("序号", style="dim", width=4)
    table.add_column("标题", style="bold", max_width=40)
    table.add_column("公众号", max_width=20)
    table.add_column("时间", max_width=12)
    table.add_column("字数", justify="right", max_width=6)

    for i, art in enumerate(articles, 1):
        table.add_row(
            str(i),
            art.title[:40],
            art.account_name,
            art.publish_time_raw or (art.publish_time.strftime("%Y-%m-%d") if art.publish_time else ""),
            str(art.word_count) if art.word_count else "-",
        )
    console.print(table)

    save_articles(articles, out_dir, keyword, formats)
    console.print(f"\n[bold green]✓ 完成！共保存 {len(articles)} 篇文章。[/bold green]")


if __name__ == "__main__":
    main()
