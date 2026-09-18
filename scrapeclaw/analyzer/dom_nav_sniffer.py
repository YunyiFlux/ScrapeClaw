"""DOM Category & Navigation Element Sniffer for ScrapeClaw.

Specialized reconnaissance and UI-driven observation loop.
Detects tabs, navigation menus, and category links in the DOM that match the user's
requested filter keywords (e.g., '科技', '数码', '游戏'), providing precise selectors
for browser_click so the agent can quickly switch from generic feeds to dedicated category views.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from html.parser import HTMLParser


class NavElement:
    def __init__(self, tag: str, attrs: Dict[str, str], text: str = ""):
        self.tag = tag
        self.attrs = attrs
        self.text = text.strip()

    @property
    def href(self) -> str:
        return self.attrs.get("href", "")

    @property
    def class_name(self) -> str:
        return self.attrs.get("class", "")

    @property
    def id_name(self) -> str:
        return self.attrs.get("id", "")

    def get_selector(self) -> str:
        """Generate a CSS selector for this navigation element."""
        if self.id_name:
            return f"#{self.id_name}"
        if self.href and len(self.href) < 60:
            clean_href = self.href.split('?')[0].rstrip('/')
            return f"{self.tag}[href*='{clean_href}']"
        if self.class_name:
            first_cls = self.class_name.split()[0]
            return f"{self.tag}.{first_cls}"
        return self.tag


class _NavHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements: List[NavElement] = []
        self._current_tag: Optional[str] = None
        self._current_attrs: Dict[str, str] = {}
        self._current_text: List[str] = []
        self._relevant_tags = {"a", "button", "li", "span", "div"}

    def handle_starttag(self, tag: str, attrs: List[tuple]):
        if tag in self._relevant_tags:
            self._current_tag = tag
            self._current_attrs = dict(attrs)
            self._current_text = []

    def handle_data(self, data: str):
        if self._current_tag:
            self._current_text.append(data)

    def handle_endtag(self, tag: str):
        if self._current_tag == tag:
            text = "".join(self._current_text).strip()
            has_nav_role = any(
                k in ("role", "aria-label") or "nav" in str(v) or "tab" in str(v)
                for k, v in self._current_attrs.items()
            )
            is_anchor_or_btn = tag in ("a", "button")
            if (is_anchor_or_btn or has_nav_role) and (text or self._current_attrs.get("href")):
                self.elements.append(NavElement(tag, self._current_attrs, text))
            self._current_tag = None
            self._current_attrs = {}
            self._current_text = []


def sniff_category_navigation(
    html_or_dom_text: str,
    filter_keywords: List[str],
) -> List[Dict[str, Any]]:
    """Sniff navigation items matching filter keywords from DOM/HTML."""
    if not html_or_dom_text or not filter_keywords:
        return []

    search_terms: List[str] = []
    for kw in filter_keywords:
        search_terms.append(kw)
        if len(kw) >= 4:
            search_terms.append(kw[:2])
            search_terms.append(kw[2:])

    candidates: List[Dict[str, Any]] = []
    seen_texts = set()

    # 1. Parse HTML structure
    parser = _NavHTMLParser()
    try:
        parser.feed(html_or_dom_text[:100000])
        for elem in parser.elements:
            elem_text = elem.text
            elem_href = elem.href
            for term in search_terms:
                if (term in elem_text or term in elem_href) and elem_text not in seen_texts:
                    seen_texts.add(elem_text)
                    selector = elem.get_selector()
                    candidates.append({
                        "label": elem_text or term,
                        "matched_keyword": term,
                        "tag": elem.tag,
                        "href": elem_href,
                        "selector": selector,
                        "recommended_action": f'browser_click(selector="{selector}")',
                    })
                    break
    except Exception:
        pass

    # 2. Fallback text pattern regex match on plain text DOM summaries
    if not candidates:
        for term in search_terms:
            pattern = re.compile(
                r"(?:\[(?:a|button|tab)\]|[<\"'])\s*([^\"'<>[\]\n]+?" + re.escape(term) + r"[^\"'<>[\]\n]*?)\s*(?:[>\"']|\((?:href|selector):?\s*([^\)]+)\))?",
                re.IGNORECASE,
            )
            for m in pattern.finditer(html_or_dom_text):
                text_label = m.group(1).strip()
                href_or_sel = m.group(2).strip() if m.group(2) else ""
                if text_label and text_label not in seen_texts and len(text_label) <= 20:
                    seen_texts.add(text_label)
                    sel = href_or_sel if href_or_sel else f"a:has-text('{text_label}')"
                    candidates.append({
                        "label": text_label,
                        "matched_keyword": term,
                        "tag": "a",
                        "href": href_or_sel if ("http" in href_or_sel or "/" in href_or_sel) else "",
                        "selector": sel,
                        "recommended_action": f'browser_click(selector="{sel}")',
                    })

    return candidates[:5]


def format_category_navigation_hint(candidates: List[Dict[str, Any]]) -> str:
    """Format navigation candidates into an actionable markdown alert."""
    if not candidates:
        return ""

    lines = [
        "\n🎯 [Category Navigation Guide] 检测到页面中包含与目标分类匹配的交互栏目/Tab：",
    ]
    for idx, c in enumerate(candidates, 1):
        label = c["label"]
        href_info = f" (URL: {c['href']})" if c["href"] else ""
        lines.append(f"  {idx}. 栏目名称: '{label}'{href_info}")
        lines.append(f"     👉 建议点击: {c['recommended_action']}")

    lines.append(
        "💡 行动指导: 用户明确要求特定分类！请立即调用 browser_click 点击上述栏目切换视图，"
        "捕获分类切换后的专属 API 请求，切勿继续在全站综合大盘数据流中抓取！\n"
    )
    return "\n".join(lines)
