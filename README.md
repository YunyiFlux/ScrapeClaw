# ScrapeClaw 🦞

> **Autonomous SPA Reverse-Engineering & Production Crawler Synthesizer Agent**  
> *Give ScrapeClaw a target URL and a natural language extraction goal. It explores the page, discovers underlying private APIs, and synthesizes standalone, high-concurrency Python crawlers with zero browser dependencies.*

[中文文档](README_CN.md)

---

## 📌 What is ScrapeClaw?

**ScrapeClaw** is an AI agent designed to reverse-engineer modern single-page applications (SPAs built with Vue, React, Next.js, etc.).

Instead of relying on heavy, resource-intensive browser automation for actual data scraping, ScrapeClaw follows a simple philosophy:
- **Browser as Probe**: An automated headless browser navigates the target, simulates human interaction, and intercepts background network traffic.
- **Pure Python Spider as Deliverable**: The agent analyzes captured traffic, prunes redundant headers, deduces pagination and client-side cryptographic signatures, and synthesizes a production-ready, standalone Python crawler (using `httpx`, `scrapy`, or `DrissionPage`).

---

## ✨ Key Features

- 🔍 **Autonomous API Discovery**: Automatically captures background XHR/Fetch calls and pins down the private API endpoint serving the required data.
- ⚡ **Multi-Engine Scaffolding**: Synthesizes standalone crawlers tailored to your needs:
  - `httpx` (lightweight, single-file asynchronous spider)
  - `scrapy` (full multi-file industrial project with settings, items, pipelines)
  - `drission` (anti-detection browser/requests hybrid)
- 📊 **Multi-Format Data Export**: Directly export data to **CSV** (with Excel BOM support), **JSONL**, or **JSON**.
- 🔐 **Client-side JS Crypto Reverse Engineering**: Captures dynamic JavaScript token/sign functions and generates decoupled Node.js signing modules (`sign.js`) alongside the crawler.
- 🛡️ **Session Persistence & CAPTCHA Support**: Supports cookie/session injection and automated Cloudflare Turnstile challenge detection and solving.
- 🧪 **Offline Physical Execution Gate**: Every synthesized crawler is executed in a sandboxed child process to verify data extraction quality before delivery.

---

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/YunyiFlux/ScrapeClaw.git
cd ScrapeClaw

# Install package in editable mode
pip install -e .

# Install required Chromium browser for the probe
playwright install chromium
```

> **Optional**: Install [Node.js](https://nodejs.org/) (v18+) if you need client-side JavaScript signature reverse engineering.

### 2. Configuration

Copy the example environment file and configure your LLM provider:

```bash
cp .env.example .env
```

Edit `.env` with your API keys:
```ini
# Example for OpenAI
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o

# Or example for Alibaba DashScope / Qwen
# DASHSCOPE_API_KEY=your_dashscope_key_here
# DASHSCOPE_MODEL=qwen-max
```

Verify your setup at any time with:
```bash
scrapeclaw doctor
```

---

## 💻 Basic Usage

### Interactive Wizard (Recommended)
Simply type `scrapeclaw` in your terminal without any arguments to launch the guided wizard:
- **Quick Mode (Default)**: Enter target URL and extraction goal, then press Enter to immediately launch.
- **Custom Mode**: Type `c` at confirmation to customize crawler engine (httpx/scrapy/drission), export format, and session credentials.
- **Navigation**: Type `b` anytime to go back to the previous step, or `q` to safely exit.

```bash
scrapeclaw
```

### CLI Command Line Mode
Give ScrapeClaw a target URL and your extraction goal in natural language:

```bash
scrapeclaw run https://quotes.toscrape.com/js/ --goal "Extract quote text, author name, and tags"
```

### Save Crawler & Export Data to CSV
Specify the output script path and data destination:

```bash
scrapeclaw run https://spa2.scrape.center/ \
  --goal "Extract movie name, score, and categories" \
  --output ./movie_spider.py \
  --data-output ./output/movies.csv \
  --format csv
```

### Generate an Industrial Scrapy Project
Generate a full Scrapy project instead of a single script:

```bash
scrapeclaw run https://news.ycombinator.com/ \
  --goal "Extract top stories title, score, and link" \
  --target-engine scrapy \
  --output ./crawlers/hn_scrapy
```

---

---

## 🐍 Python SDK Usage

ScrapeClaw can be imported directly into your Python scripts or data pipelines:

### Synchronous One-liner
```python
import scrapeclaw

crawler = scrapeclaw.synthesize(
    url="https://spa2.scrape.center/",
    goal="Extract movie name, score, and categories",
    engine="httpx",
)

print(crawler.code)
crawler.save("./my_spider.py")
```

### Asynchronous One-liner
```python
import scrapeclaw

crawler = await scrapeclaw.synthesize_async(
    url="https://spa2.scrape.center/",
    goal="Extract movie name, score, and categories",
)
```

### Context Manager (Reuse Browser Probe)
```python
from scrapeclaw import AsyncScrapeClaw

async with AsyncScrapeClaw(headless=True) as client:
    res1 = await client.synthesize("https://example.com/page1", "Extract table")
    res2 = await client.synthesize("https://example.com/page2", "Extract comments")
```

---

## 💡 Real-World Showcase

Below are two real-world examples demonstrating what ScrapeClaw synthesizes without manual reverse engineering:

### Example 1: SPA with Client-Side JS Dynamic Token (`spa2.scrape.center`)

- **Target Scenario**: The target API (`/api/movie/`) requires a dynamic client-side signature (`token = sha1(path + timestamp + offset)`).
- **Execution**:
  ```bash
  scrapeclaw run https://spa2.scrape.center/ \
    --goal "Extract movie name, score, and categories" \
    --output ./movie_spider.py \
    --data-output ./output/movies.json \
    --format json
  ```
- **What ScrapeClaw Synthesized**:
  1. **Decoupled Signer (`sign_spa2.js`)**: Isolated Node.js script reverse-engineered from page bundle:
     ```javascript
     const crypto = require('crypto');
     const ts = Math.round(Date.now() / 1000).toString();
     const token = crypto.createHash('sha1').update(`/api/movie,${offset},${ts}`).digest('hex');
     ```
  2. **Standalone Async Spider (`movie_spider.py`)**: Pure Python `httpx` spider that queries `/api/movie/?limit=10&offset=0&token=...` at wire speed with zero browser footprint.
- **Extracted Data Snippet (`output/movies.json`)**:
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

### Example 2: Aggregated News & Discussion Metrics (`news.ycombinator.com`)

- **Target Scenario**: Hacker News front-page top stories with real-time community engagement scores and discussion links.
- **Execution**:
  ```bash
  scrapeclaw run https://news.ycombinator.com/ \
    --goal "Extract top stories: title, url, score, and comment count" \
    --output ./hn_spider.py \
    --data-output ./output/hn_top.json \
    --format json
  ```
- **What ScrapeClaw Synthesized**:
  - `hn_spider.py`: Standalone pure Python crawler with automatic DOM element alignment, robust regex parsing, and structured data serialization.
- **Extracted Data Snippet (`output/hn_top.json`)**:
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

## 📄 License

This project is licensed under the [MIT License](LICENSE).
