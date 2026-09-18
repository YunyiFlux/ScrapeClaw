"""Goal Parser & Semantic Intent Extractor for ScrapeClaw.

Domain constraints parser for task goals.
Extracts structured ScrapeGoalSpec from free-form natural language goals,
including cardinality, ordinals, top-k limits, sorting metrics, and filter conditions.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from scrapeclaw.core.goal_spec import CardinalityMode, ScrapeGoalSpec

CHINESE_NUM_MAP: Dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
}

ENGLISH_ORDINAL_MAP: Dict[str, int] = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
}

METRIC_MAP: Dict[str, str] = {
    "播放量": "view_count",
    "播放数": "view_count",
    "观看量": "view_count",
    "点击量": "view_count",
    "浏览量": "view_count",
    "点赞数": "like_count",
    "点赞量": "like_count",
    "点赞": "like_count",
    "收藏数": "favorite_count",
    "收藏量": "favorite_count",
    "投币数": "coin_count",
    "评论数": "comment_count",
    "弹幕数": "danmaku_count",
    "价格": "price",
    "金额": "price",
    "发布时间": "publish_time",
    "时间": "publish_time",
    "日期": "publish_date",
    "粉丝数": "follower_count",
    "热度": "heat_score",
    "排名": "rank",
}

FIELD_PATTERNS: List[Tuple[str, str]] = [
    (r"(?:视频|文章|商品|帖子)?标题", "title"),
    (r"(?:up主名称|up主|作者名称|作者|发布者|创作者|用户)", "up_name"),
    (r"(?:播放量|播放数|观看量|点击量)", "view_count"),
    (r"(?:点赞数|点赞量|获赞数)", "like_count"),
    (r"(?:评论数|回帖数)", "comment_count"),
    (r"(?:收藏数|收藏量)", "favorite_count"),
    (r"(?:链接|url|网址)", "url"),
    (r"(?:发布时间|创建时间|更新时间)", "publish_time"),
    (r"(?:简介|描述|正文|内容)", "content"),
    (r"(?:封面|头像|图片)", "cover_image"),
    (r"(?:价格|售价|原价)", "price"),
    (r"(?:排名|榜单排名|名次)", "rank"),
]


def _parse_number(num_str: str) -> Optional[int]:
    """Convert Chinese or Arabic numeral string to integer."""
    clean = num_str.strip().lower()
    if clean.isdigit():
        return int(clean)
    ord_m = re.match(r"^(\\d+)(?:st|nd|rd|th)$", clean)
    if ord_m:
        return int(ord_m.group(1))
    if clean in CHINESE_NUM_MAP:
        return CHINESE_NUM_MAP[clean]
    if clean in ENGLISH_ORDINAL_MAP:
        return ENGLISH_ORDINAL_MAP[clean]
    return None


def parse_goal_spec(goal_text: str) -> ScrapeGoalSpec:
    """Parse raw goal text into a structured ScrapeGoalSpec."""
    text = (goal_text or "").strip()
    if not text:
        return ScrapeGoalSpec(raw_goal="")

    spec = ScrapeGoalSpec(raw_goal=text)

    # 1. 识别序数提取 (Ordinal Extraction)
    ordinal_match = re.search(
        r"(?:第\s*([一二三四五六七八九十\d]+)\s*[名个条位项]?|(?:the\s+)?(\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth)(?:\s+most|\s+latest|\s+highest|\s+video|\s+item|\b))",
        text,
        re.IGNORECASE,
    )
    if ordinal_match:
        matched_str = ordinal_match.group(1) or ordinal_match.group(2)
        if matched_str:
            idx = _parse_number(matched_str)
            if idx is not None and idx > 0:
                spec.cardinality = CardinalityMode.ORDINAL
                spec.ordinal_index = idx
                spec.limit = 1

    # 2. 识别 Top-K 截断 (Top-K Extraction)
    if spec.cardinality == CardinalityMode.ALL:
        top_k_match = re.search(
            r"(?:(?:前|top|Top|TOP)\s*([一二三四五六七八九十\d]+)\s*[名个条位项]?|(?:最多|仅获取|至多)\s*([一二三四五六七八九十\d]+)\s*[名个条位项]?)",
            text,
        )
        if top_k_match:
            matched_str = top_k_match.group(1) or top_k_match.group(2)
            k = _parse_number(matched_str)
            if k is not None and k > 0:
                spec.cardinality = CardinalityMode.TOP_K
                spec.limit = k

    # 3. 识别极值单条 (Superlative Single Item)
    if spec.cardinality == CardinalityMode.ALL:
        single_match = re.search(
            r"(?:最[高大多大新热好长短低少慢早小]\s*的?\s*一\s*[个条部篇位项]|the\s+(?:latest|newest|highest|top|most)\s+\w+)",
            text,
            re.IGNORECASE,
        )
        if single_match:
            spec.cardinality = CardinalityMode.SINGLE
            spec.limit = 1

    # 4. 识别排序指标 (Sorting Metric)
    for kw, metric_key in METRIC_MAP.items():
        if kw in text:
            spec.sort_metric = metric_key
            break

    if any(term in text for term in ["升序", "从低到高", "最低", "最早", "最少", "ascending", "asc"]):
        spec.sort_order = "asc"
    elif any(term in text for term in ["降序", "从高到低", "最高", "最新", "最多", "descending", "desc"]):
        spec.sort_order = "desc"

    # 5. 识别分类与过滤关键词 (Filter Keywords)
    filter_match = re.findall(
        r"(?:中|关于|从|在)?([一-龟a-zA-Z0-9_\-\s]{2,10}?)(?:类|分类|频道|专区|板块|区)",
        text,
    )
    stop_words = {"热门", "视频", "排行", "排行榜", "热门视频", "视频排行", "全部"}
    for item in filter_match:
        cleaned = item.strip()
        cleaned = re.sub(r"^(?:热门|视频|排行榜|榜单|中|从|关于)+", "", cleaned).strip()
        if cleaned and cleaned not in stop_words and len(cleaned) >= 2:
            if cleaned not in spec.filter_keywords:
                spec.filter_keywords.append(cleaned)

    # 6. 提取目标字段 (Target Fields)
    for pat, field_name in FIELD_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            if field_name not in spec.target_fields:
                spec.target_fields.append(field_name)

    # 英文目标字段支持
    eng_field_map = {
        "title": "title",
        "author": "up_name",
        "uploader": "up_name",
        "view": "view_count",
        "like": "like_count",
        "url": "url",
        "link": "url",
        "price": "price",
    }
    for eng_word, std_field in eng_field_map.items():
        if re.search(rf"\b{eng_word}\b", text, re.IGNORECASE):
            if std_field not in spec.target_fields:
                spec.target_fields.append(std_field)

    return spec
