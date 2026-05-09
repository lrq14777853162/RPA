# 微信公众号文章爬虫（RPA 模式）

基于 **Python + Playwright** 的公众号文章抓取工具，采用 **RPA（机器人流程自动化）** 方式直接操控微信 Web（`wx.qq.com`），模拟人工登录、搜索、翻页、阅读，按关键词抓取公开文章。

> **无需调用任何第三方搜索引擎**，直接驱动真实微信 Web 界面完成所有操作。

---

## 工作流程（RPA）

```
启动程序
  │
  ▼
打开浏览器 → 访问 wx.qq.com
  │
  ├─ 有效 session（已登录）──→ 跳过扫码
  │
  └─ 未登录 ─→ 保存二维码图片
                 │
                 ▼
            用户扫码 + 手机确认
                 │
                 ▼
           检测到登录成功
  │
  ▼
在搜索栏输入关键词（逐字模拟人工输入）
  │
  ▼
切换到「文章」标签
  │
  ▼
逐页提取文章列表（元数据）
  │
  ▼
逐篇打开文章页（mp.weixin.qq.com），抓取正文
  │
  ▼
保存 JSON / CSV / SQLite + 保存 session
```

---

## 环境要求

- Python 3.10+
- Playwright（含 Chromium）

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 首次运行（需扫码登录）

```bash
python main.py 人工智能
```

程序会打开浏览器窗口并在 `output/qrcode.png` 保存二维码，用微信扫码后在手机点击「登录」，程序自动继续。

### 3. 后续运行（session 复用，可免扫码）

```bash
# session 默认保存在 .session/ 目录
python main.py 人工智能 --headless --session-dir .session
```

### 4. 更多示例

```bash
# 抓取 3 页，只输出 JSON
python main.py 人工智能 --pages 3 --format json

# 只保存元数据（不进文章页，速度快）
python main.py 人工智能 --no-content

# 查看所有选项
python main.py --help
```

---

## 配置文件

编辑 `config.yaml` 进行全局配置：

```yaml
scraper:
  max_pages: 5          # 最多采集页数
  fetch_content: true   # 是否抓取正文
  headless: false       # 首次运行必须 false（需扫码）
  delay_min: 1.5        # 操作最小间隔（秒）
  delay_max: 3.5        # 操作最大间隔（秒）
  timeout: 30000        # 超时（毫秒）
  session_dir: .session # session 保存目录

storage:
  output_dir: output
  formats:
    - json
    - csv
```

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

1. **RPA 直接操控**：程序模拟人工在微信 Web 中搜索，无需任何第三方搜索入口。
2. **首次须有头模式**：扫码登录需要看到浏览器窗口（`headless: false`）。
3. **Session 持久化**：登录后 session 自动保存，下次可免扫码直接运行。
4. **合理延迟**：默认设置了人工操作节奏的随机延迟，勿随意缩短。
5. **文章有效期**：微信文章链接有时效性，建议及时抓取正文。

---

## 项目结构

```
RPA/
├── main.py                  # CLI 入口（Click + Rich）
├── config.yaml              # 配置文件
├── requirements.txt         # 依赖列表
├── .gitignore
├── wechat_scraper/
│   ├── __init__.py
│   ├── models.py            # Pydantic 数据模型（Article）
│   ├── scraper.py           # RPA 核心：登录 → 搜索 → 采集 → 正文
│   ├── storage.py           # 存储后端（JSON / CSV / SQLite）
│   └── utils.py             # 工具函数
├── output/                  # 默认输出目录（运行后生成）
└── .session/                # Session 目录（运行后生成）
```
