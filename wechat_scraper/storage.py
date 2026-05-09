"""Storage backends: JSON, CSV, SQLite."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Sequence

from rich.console import Console

from .models import Article

console = Console()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ── JSON ──────────────────────────────────────────────────────────────────────

def save_json(articles: Sequence[Article], filepath: Path) -> None:
    """将文章列表保存为 JSON 文件（追加模式）。"""
    _ensure_dir(filepath.parent)

    existing: list[dict] = []
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            existing = []

    existing.extend(a.to_dict() for a in articles)
    filepath.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]JSON 已保存 → {filepath}[/green]")


# ── CSV ───────────────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "title",
    "url",
    "account_name",
    "account_id",
    "summary",
    "publish_time",
    "publish_time_raw",
    "cover_image",
    "content",
    "word_count",
    "keyword",
    "scraped_at",
    "page_num",
]


def save_csv(articles: Sequence[Article], filepath: Path) -> None:
    """将文章列表保存为 CSV 文件（追加模式）。"""
    _ensure_dir(filepath.parent)

    file_exists = filepath.exists()
    with filepath.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for article in articles:
            row = article.to_dict()
            # 将 list 字段转为字符串，避免 CSV 问题
            row["images"] = "; ".join(article.images)
            writer.writerow(row)
    console.print(f"[green]CSV 已保存 → {filepath}[/green]")


# ── SQLite ────────────────────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    url           TEXT UNIQUE,
    account_name  TEXT,
    account_id    TEXT,
    summary       TEXT,
    publish_time  TEXT,
    publish_time_raw TEXT,
    cover_image   TEXT,
    content       TEXT,
    content_html  TEXT,
    images        TEXT,
    word_count    INTEGER DEFAULT 0,
    keyword       TEXT,
    scraped_at    TEXT,
    page_num      INTEGER DEFAULT 1
);
"""

_INSERT_SQL = """
INSERT OR IGNORE INTO articles
    (title, url, account_name, account_id, summary, publish_time,
     publish_time_raw, cover_image, content, content_html, images,
     word_count, keyword, scraped_at, page_num)
VALUES
    (:title, :url, :account_name, :account_id, :summary, :publish_time,
     :publish_time_raw, :cover_image, :content, :content_html, :images,
     :word_count, :keyword, :scraped_at, :page_num);
"""


def save_sqlite(articles: Sequence[Article], filepath: Path) -> None:
    """将文章列表保存到 SQLite 数据库（追加模式，URL 唯一索引去重）。"""
    _ensure_dir(filepath.parent)

    conn = sqlite3.connect(filepath)
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()

        for article in articles:
            d = article.to_dict()
            d["images"] = "; ".join(article.images)
            conn.execute(_INSERT_SQL, d)

        conn.commit()
    finally:
        conn.close()

    console.print(f"[green]SQLite 已保存 → {filepath}[/green]")


# ── 统一入口 ──────────────────────────────────────────────────────────────────

def save_articles(
    articles: Sequence[Article],
    output_dir: str | Path,
    keyword: str,
    formats: list[str],
) -> None:
    """根据配置的格式列表保存文章。"""
    output_dir = Path(output_dir)
    # 文件名以关键词+日期命名（避免特殊字符）
    safe_keyword = "".join(c if c.isalnum() or c in "-_" else "_" for c in keyword)

    if "json" in formats:
        save_json(articles, output_dir / f"{safe_keyword}.json")

    if "csv" in formats:
        save_csv(articles, output_dir / f"{safe_keyword}.csv")

    if "sqlite" in formats:
        save_sqlite(articles, output_dir / "wechat_articles.db")
