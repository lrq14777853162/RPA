"""Data models for scraped WeChat articles."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class Article(BaseModel):
    """Represents a single WeChat public account article."""

    # ── 基本元数据（搜索结果页即可获取） ──────────────────────────
    title: str = Field(description="文章标题")
    url: str = Field(description="文章原始链接")
    account_name: str = Field(default="", description="公众号名称")
    account_id: str = Field(default="", description="公众号 ID / 微信号")
    summary: str = Field(default="", description="文章摘要")
    publish_time: Optional[datetime] = Field(default=None, description="发布时间")
    publish_time_raw: str = Field(default="", description="发布时间原始字符串")
    cover_image: str = Field(default="", description="封面图片 URL")

    # ── 正文内容（访问文章页面后填充） ───────────────────────────
    content: str = Field(default="", description="文章正文（纯文本）")
    content_html: str = Field(default="", description="文章正文（HTML）")
    images: list[str] = Field(default_factory=list, description="正文图片列表")
    word_count: int = Field(default=0, description="正文字数")

    # ── 采集元数据 ────────────────────────────────────────────────
    keyword: str = Field(default="", description="搜索关键词")
    scraped_at: datetime = Field(
        default_factory=datetime.now, description="采集时间"
    )
    page_num: int = Field(default=1, description="来源搜索结果页码")

    def to_dict(self) -> dict:
        data = self.model_dump()
        # 将 datetime 转为 ISO 字符串，方便序列化
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data
