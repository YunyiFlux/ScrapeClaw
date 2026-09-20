# ScrapeClaw 🦞 (中文版)

> **AI 驱动的现代复杂 SPA 网页“自主逆向探查与私有接口爬虫合成” Agent**  
> *输入一个网址与自然语言采集目标，Agent 自主探查页面业务流、捕获私有 API，最终交付零浏览器依赖的高并发纯 Python 爬虫。*

[English Version](README.md)

---

## 📌 什么是 ScrapeClaw？

**ScrapeClaw** 是一个面向现代复杂 Web 应用（React/Vue/Angular/Next.js 等单页应用 SPA）的**深度逆向与爬虫自动化合成 AI Agent**。

传统爬虫往往面临两个难点：无头浏览器模拟点击太重太慢、人工抓包逆向耗时耗力。ScrapeClaw 贯彻核心设计哲学：
- **浏览器为探针进场**：仅在探测阶段使用无头浏览器驱动页面，拦截后台完整 XHR/Fetch 网络流量；
- **纯净 API 爬虫退场**：Agent 自动剪枝冗余 Header、推导分页规则与前端 JS 动态签名，合成出生产级、免浏览器依赖的高并发纯 Python 爬虫（支持 `httpx`、`scrapy` 或 `DrissionPage`）。

---

## ✨ 核心特性

- 🔍 **自主 API 发现与定位**：自动截获后台私有数据接口，并根据目标语义匹配对应数据节点。
- ⚡ **多爬虫引擎脚手架**：支持一键合成多种形态的爬虫产物：
  - `httpx`（轻量单文件异步爬虫，适合脚本化任务）
  - `scrapy`（工业级多文件工程，含 settings/items/pipelines）
  - `drission`（DrissionPage 抗检测模式）
- 📊 **生产级多格式导出**：原生支持导出为带 BOM 的 **CSV**（Excel 友好无乱码）、**JSONL** 与 **JSON**。
- 🔐 **客户端 JS 逆向与动态签名**：自动捕获前端加密操作并生成解耦的 Node.js 独立签名模块（`sign.js`）。
- 🛡️ **会话流转与人机对抗**：支持一键载入已登录 Cookies 凭据，并具备 Cloudflare Turnstile 挑战自动检测与求解能力。
- 🧪 **物理离线验证门禁**：每个合成的爬虫脚本都会在本地子进程沙箱中实际运行验证，确保交付代码 100% 可用。

---

## 🚀 快速上手

### 1. 安装项目

```bash
# 克隆代码仓库
git clone https://github.com/YunyiFlux/ScrapeClaw.git
cd ScrapeClaw

# 以可编辑模式安装依赖
pip install -e .

# 安装探针所需的 Chromium 浏览器
playwright install chromium
```

> **可选提示**：如需执行前端 JS 动态签名逆向，请确保本地已安装 [Node.js](https://nodejs.org/)（v18+）。

### 2. 配置环境

复制环境变量示例文件并配置大模型 API Key：

```bash
cp .env.example .env
```

在 `.env` 中填写您的模型密钥（支持通义千问 Qwen、DeepSeek、OpenAI、Claude 或本地 Ollama）：
```ini
# 以通义千问 (DashScope) 为例
DASHSCOPE_API_KEY=your_dashscope_key_here
DASHSCOPE_MODEL=qwen-max

# 或使用 OpenAI
# OPENAI_API_KEY=your_openai_key_here
# OPENAI_MODEL=gpt-4o
```

随时可通过自检命令确认环境是否完整：
```bash
scrapeclaw doctor
```

---

## 💻 基础使用指南

### 交互式引导向导 (推荐)
在终端直接输入 `scrapeclaw` 即可启动交互引导向导：
- **极速模式 (默认推荐)**：仅需依次输入目标网址与采集目标，按回车即可直接开跑！
- **定制模式**：在确认环节输入 `c`，即可自由定制爬虫引擎（httpx/scrapy/drission）、数据导出格式（JSON/CSV/JSONL）与会话凭据。
- **自由掌控**：全程支持输入 `b` 回退至上一步修改，输入 `q` 安全退出。

```bash
scrapeclaw
```

### 命令行脚本模式
传入目标网页 URL 与您要抓取的自然语言目标：

```bash
scrapeclaw run https://quotes.toscrape.com/js/ --goal "抓取名言内容、作者姓名以及分类标签"
```

### 2. 指定爬虫输出文件并导出 CSV 数据
```bash
scrapeclaw run https://spa2.scrape.center/ \
  --goal "抓取电影名称、评分与分类标签" \
  --output ./movie_spider.py \
  --data-output ./output/movies.csv \
  --format csv
```

### 3. 一键生成工业级 Scrapy 项目
```bash
scrapeclaw run https://news.ycombinator.com/ \
  --goal "抓取热门帖子的标题、得分与链接" \
  --target-engine scrapy \
  --output ./crawlers/hn_scrapy
```

---

---

## 🐍 Python SDK 使用指南

ScrapeClaw 提供了开箱即用的原生 Python SDK，方便直接嵌入现有脚本或数据处理管道：

### 同步调用
```python
import scrapeclaw

crawler = scrapeclaw.synthesize(
    url="https://spa2.scrape.center/",
    goal="抓取电影名称与评分",
    engine="httpx",
)

print(crawler.code)
crawler.save("./my_spider.py")
```

### 异步调用
```python
import scrapeclaw

crawler = await scrapeclaw.synthesize_async(
    url="https://spa2.scrape.center/",
    goal="抓取电影名称与评分",
)
```

### 上下文管理器（复用探针浏览器）
```python
from scrapeclaw import AsyncScrapeClaw

async with AsyncScrapeClaw(headless=True) as client:
    res1 = await client.synthesize("https://example.com/page1", "抓取数据列表")
    res2 = await client.synthesize("https://example.com/page2", "抓取评论信息")
```

---

## 💡 真实用例参考 (Real-World Showcase)

以下为 ScrapeClaw 在真实测试场景中自主逆向并合成爬虫的典型案例：

### 案例 1：带前端 JS 动态签名加密的 SPA 逆向 (`spa2.scrape.center`)

- **目标场景**：目标电影列表私有接口（`/api/movie/`）受前端 JavaScript 动态签名校验保护（`token = sha1(path + timestamp + offset)`）。
- **运行命令**：
  ```bash
  scrapeclaw run https://spa2.scrape.center/ \
    --goal "抓取电影名称、评分与分类标签" \
    --output ./movie_spider.py \
    --data-output ./output/movies.json \
    --format json
  ```
- **ScrapeClaw 自动合成产物**：
  1. **独立解耦签名模块 (`sign_spa2.js`)**：从前端混淆代码中逆向提炼出独立的 Node.js 签名生成脚本：
     ```javascript
     const crypto = require('crypto');
     const ts = Math.round(Date.now() / 1000).toString();
     const token = crypto.createHash('sha1').update(`/api/movie,${offset},${ts}`).digest('hex');
     ```
  2. **轻量异步爬虫 (`movie_spider.py`)**：基于 `httpx` 异步请求底层 API，自动调度签名脚本生成有效 token，无需常驻真实浏览器，高并发秒级拉取。
- **爬取数据片段 (`output/movies.json`)**：
  ```json
  [
    {
      "name": "霸王别姬 - Farewell My Concubine",
      "categories": ["剧情", "爱情"],
      "score": 9.5
    },
    {
      "name": "这个杀手不太冷 - Léon",
      "categories": ["剧情", "动作", "犯罪"],
      "score": 9.5
    }
  ]
  ```

### 案例 2：新闻聚合与热度指标全量抓取 (`news.ycombinator.com`)

- **目标场景**：实时抓取 Hacker News 首页热门技术资讯、外部链接、社区点赞数与评论讨论数。
- **运行命令**：
  ```bash
  scrapeclaw run https://news.ycombinator.com/ \
    --goal "抓取热门帖子的标题、链接、得分以及评论数" \
    --output ./hn_spider.py \
    --data-output ./output/hn_top.json \
    --format json
  ```
- **ScrapeClaw 自动合成产物**：
  - `hn_spider.py`：单文件纯 Python 高效解析爬虫，具备 DOM 结构自动映射、正则降级与结构化输出。
- **爬取数据片段 (`output/hn_top.json`)**：
  ```json
  [
    {
      "title": "Bonsai 2 27B: Near-Lossless Compression in a 9x Smaller Footprint",
      "url": "https://prismml.com/news/bonsai-2-27b",
      "score": 142,
      "comment_count": 38
    },
    {
      "title": "Bend – A language that blocks AI mistakes via proof, on CPU and GPU",
      "url": "https://bend-lang.com/",
      "score": 289,
      "comment_count": 94
    }
  ]
  ```

---

## 📄 开源许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
