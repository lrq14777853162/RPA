"""Utility helpers for the scraper."""

from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime, timedelta
from typing import Optional


def random_delay(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    """阻塞式随机延迟（在同步上下文中使用）。"""
    time.sleep(random.uniform(min_sec, max_sec))


async def async_random_delay(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    """异步随机延迟。"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


def parse_publish_time(raw: str) -> Optional[datetime]:
    """
    尝试将微信文章或搜索结果中的时间字符串解析为 datetime。

    常见格式：
      - "1天前" / "2小时前" / "30分钟前"
      - "2024-01-15"
      - "01月15日"
    """
    raw = raw.strip()
    now = datetime.now()

    # 几分钟前
    m = re.match(r"(\d+)分钟前", raw)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    # 几小时前
    m = re.match(r"(\d+)小时前", raw)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    # N 天前
    m = re.match(r"(\d+)天前", raw)
    if m:
        return now - timedelta(days=int(m.group(1)))

    # 昨天
    if "昨天" in raw:
        return now - timedelta(days=1)

    # YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # MM月DD日（当年）
    m = re.match(r"(\d{1,2})月(\d{1,2})日", raw)
    if m:
        try:
            return datetime(now.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    return None


def clean_text(text: str) -> str:
    """去除多余空白和不可见字符。"""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def count_chinese_words(text: str) -> int:
    """统计中文字数（中文字符 + 英文单词）。"""
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"\b[a-zA-Z]+\b", text))
    return chinese + english_words
