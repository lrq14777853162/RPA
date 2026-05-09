# 微信公众号文章爬虫

基于 **Python + Playwright** 的公众号文章抓取工具。  
通过 **搜狗微信搜索**（`weixin.sogou.com`）按关键词搜索，仅抓取公开可访问的文章，无需微信账号登录。

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 关键词搜索 | 搜狗微信搜索入口，返回真实公众号文章 |
| 分页采集 | 支持多页翻页，可配置最大页数 |
| 正文抓取 | 自动跟进文章页面，提取正文文本、HTML、图片列表 |
| 多格式保存 | JSON / CSV / SQLite，可按需选择 |
| 防检测 | 随机延迟、随机 UA、隐藏 webdriver 特征 |
| 验证码处理 | 自动检测风控页面并等待重试 |
| 富文本日志 | 使用 Rich 输出彩色进度和结果表格 |

---

## 环境要求

- Python 3.10+
- Playwright（含 Chromium）

---

## 快速开始

### 1. 安装依赖

\`\`\`bash
pip install -r requirements.txt
playwright install chromium
\`\`\`

### 2. 运行爬虫

\`\`\`bash
# 基本用法：搜索关键词，爬取默认 5 页，输出 JSON + CSV
python main.py 人工智能

# 指定页数和格式
python main.py 人工智能 --pages 3 --format json --format csv

# 只抓元数据，不进入文章页面（更快）
python main.py 人工智能 --no-content

# 有头模式调试（可以看到浏览器操作）
python main.py 人工智能 --headful

# 查看所有选项
python main.py --help
\`\`\`

### 3. 查看输出

默认输出到 `output/` 目录：

\`\`\`
output/
├── 人工智能.json   # 完整文章数据（JSON 格式）
└── 人工智能.csv    # 表格格式（可用 Excel 打开）
\`\`\`

---

## 配置文件

编辑 `config.yaml` 进行全局配置：

\`\`\`yaml
scraper:
  max_pages: 5          # 最多爬取页数
  fetch_content: true   # 是否抓取正文
  headless: true        # 无头模式
  delay_min: 2.0        # 请求最小间隔（秒）
  delay_max: 5.0        # 请求最大间隔（秒）
  timeout: 30000        # 超时（毫秒）

storage:
  output_dir: output
  formats:
    - json
    - csv
\`\`\`

---

## 输出字段说明

| 字段 | 说明 |
|------|------|
| `title` | 文章标题 |
| `url` | 文章链接（微信原始链接） |
| `account_name` | 公众号名称 |
| `summary` | 文章摘要 |
| `publish_time` | 发布时间（ISO 8601） |
| `cover_image` | 封面图片 URL |
| `content` | 正文纯文本 |
| `content_html` | 正文 HTML |
| `images` | 正文图片链接列表 |
| `word_count` | 正文字数 |
| `keyword` | 搜索关键词 |
| `scraped_at` | 采集时间 |

---

## 注意事项

1. **仅抓公开文章**：所有文章均通过搜狗微信公开索引获取，无需登录。  
2. **请遵守 robots.txt 及服务条款**：合理设置 `delay_min` / `delay_max`，避免高频请求。  
3. **验证码风控**：如遇频繁拦截，可增大延迟或切换网络环境，也可使用 `--headful` 手动过验证码。  
4. **文章有效期**：微信文章链接有时效性，建议及时采集完整正文。

---

## 项目结构

\`\`\`
RPA/
├── main.py                  # CLI 入口
├── config.yaml              # 配置文件
├── requirements.txt         # 依赖列表
├── wechat_scraper/
│   ├── __init__.py
│   ├── models.py            # 数据模型（Pydantic）
│   ├── scraper.py           # 核心爬虫逻辑
│   ├── storage.py           # 存储后端（JSON/CSV/SQLite）
│   └── utils.py             # 工具函数
└── output/                  # 默认输出目录（运行后生成）
\`\`\`
