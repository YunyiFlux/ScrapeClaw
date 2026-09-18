"""Constraint Policy & Data Validation Gate for ScrapeClaw.

Execution gate constraint policy and boundary inspection.
Provides:
1. Strict semantic validation of crawler sandbox extraction results against ScrapeGoalSpec.
2. Structured violation reporting for agent self-healing.
3. Safe fallback data slicing before final disk persistence (CSV, JSON, JSONL).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from scrapeclaw.core.goal_spec import CardinalityMode, ScrapeGoalSpec

logger = logging.getLogger(__name__)


class ConstraintViolation(BaseModel):
    """Structured constraint violation event."""
    kind: str = Field(description="Violation category (e.g. cardinality_mismatch, missing_fields)")
    severity: str = Field(default="warning", description="warning or error")
    summary: str = Field(description="Brief human-readable summary")
    detail: str = Field(description="Detailed diagnostic explanation with fix recommendations")

    def to_prompt_hint(self) -> str:
        """Format as actionable feedback hint for LLM agent correction."""
        return f"[Goal Alignment Alert: {self.kind.upper()}] {self.summary}: {self.detail}"



# Known distinct category markers for contamination detection
MUTUALLY_EXCLUSIVE_CATEGORIES = {
    "科技数码": {
        "positive": ["科技", "数码", "手机", "电脑", "硬件", "芯片", "ai", "测评", "评测", "系统", "算法", "程序", "显卡", "iphone", "apple", "华为", "小米", "英伟达", "深度视频", "技术", "科普"],
        "negative": ["动画", "动漫", "鸣潮", "原神", "生活", "做饭", "炒烙饼丝", "美食", "日常", "搞笑", "幽默", "母婴", "八卦", "鬼畜", "穿搭", "恋爱", "婚恋", "逼疯孩子"],
    },
    "科技": {
        "positive": ["科技", "数码", "技术", "ai", "芯片", "硬件", "手机", "电脑", "科普", "iphone"],
        "negative": ["动画", "动漫", "鸣潮", "做饭", "美食", "日常", "搞笑", "八卦", "鬼畜", "母婴", "育儿"],
    },
    "游戏": {
        "positive": ["游戏", "电竞", "通关", "steam", "鸣潮", "原神", "黑神话", "攻略", "实况", "主机"],
        "negative": ["数码测评", "股票", "炒股", "做饭", "美食", "母婴", "美妆"],
    },
}


def check_category_contamination(
    data: List[Dict[str, Any]],
    spec: Optional[ScrapeGoalSpec],
) -> Optional[ConstraintViolation]:
    """Check if extracted items contain cross-category contamination noise."""
    if not spec or not spec.filter_keywords or not data:
        return None

    # Find matching category profile
    matched_profile = None
    for kw in spec.filter_keywords:
        for cat_name, profile in MUTUALLY_EXCLUSIVE_CATEGORIES.items():
            if kw in cat_name or cat_name in kw:
                matched_profile = (cat_name, profile)
                break
        if matched_profile:
            break

    if not matched_profile:
        return None

    cat_name, profile = matched_profile
    negatives = profile["negative"]
    positives = profile["positive"]

    contaminated_samples = []
    for item in data[:10]:
        title = str(item.get("title", "")).lower()
        tname = str(item.get("tname", "")).lower()
        cat = str(item.get("category", "")).lower()
        combined_text = f"{title} {tname} {cat}"

        has_neg = any(neg in combined_text for neg in negatives)
        has_pos = any(pos in combined_text for pos in positives)

        if has_neg and not has_pos:
            contaminated_samples.append(item.get("title") or combined_text[:30])

    if contaminated_samples:
        samples_str = "、".join(f"'{s}'" for s in contaminated_samples[:3])
        return ConstraintViolation(
            kind="category_contamination",
            severity="error",
            summary=f"Extracted data contains non-target category noise for '{cat_name}'",
            detail=(
                f"Extracted results contain obvious cross-category contamination items: {samples_str}. "
                f"This proves the crawler is querying the generic all-category feed instead of the specific '{cat_name}' channel! "
                f"Action: You MUST use browser_inspect_dom to find the '{cat_name}' tab/link, "
                f"and call browser_click to switch to the dedicated category view to obtain the genuine category API."
            ),
        )
    return None


def validate_extracted_data(
    data: List[Dict[str, Any]],
    spec: Optional[ScrapeGoalSpec],
) -> List[ConstraintViolation]:
    """Validate extracted crawler results against the task's ScrapeGoalSpec.
    
    Returns a list of ConstraintViolation events (empty if fully compliant).
    """
    if spec is None or not spec.is_constrained():
        return []

    violations: List[ConstraintViolation] = []
    count = len(data)

    # 1. 检查空结果
    if count == 0:
        violations.append(
            ConstraintViolation(
                kind="empty_data",
                severity="error",
                summary="No items extracted",
                detail="The crawler returned an empty list. Ensure selectors or API unpacking logic match the response structure.",
            )
        )
        return violations

    # 2. 检查基数/数量违背 (Cardinality Violations)
    if spec.cardinality == CardinalityMode.ORDINAL and spec.ordinal_index:
        if count != 1:
            violations.append(
                ConstraintViolation(
                    kind="cardinality_mismatch",
                    severity="error",
                    summary=f"Expected exact single item at rank {spec.ordinal_index}, but received {count} items",
                    detail=(
                        f"The user goal explicitly asked for ordinal position #{spec.ordinal_index} "
                        f"(e.g. '播放量第{spec.ordinal_index}的'). The final output array must contain ONLY this 1 item! "
                        f"In your crawler script, slice the sorted list to: "
                        f"`output_data = [sorted_items[{spec.ordinal_index - 1}]]` before outputting."
                    ),
                )
            )

    elif spec.cardinality == CardinalityMode.TOP_K and spec.limit:
        if count > spec.limit:
            violations.append(
                ConstraintViolation(
                    kind="cardinality_mismatch",
                    severity="warning",
                    summary=f"Expected Top {spec.limit} items, but received {count} items",
                    detail=(
                        f"The user goal specified Top {spec.limit} items. "
                        f"Slice the sorted array: `output_data = sorted_items[:{spec.limit}]` before outputting."
                    ),
                )
            )

    elif spec.cardinality == CardinalityMode.SINGLE:
        if count != 1:
            violations.append(
                ConstraintViolation(
                    kind="cardinality_mismatch",
                    severity="warning",
                    summary=f"Expected single superlative item, but received {count} items",
                    detail="The user requested a single superlative record (highest/latest). Slice to 1 item.",
                )
            )

    # 2.5 检查分类纯度与跨分区杂质 (Category Purity & Cross-Contamination)
    purity_violation = check_category_contamination(data, spec)
    if purity_violation:
        violations.append(purity_violation)

    # 3. 检查主要目标字段覆盖率 (Target Fields Coverage)
    if spec.target_fields and count > 0:
        first_item = data[0]
        item_keys = set(first_item.keys())
        # 简单归一化匹配字段
        missing = []
        for field in spec.target_fields:
            if not any(field in k.lower() or k.lower() in field for k in item_keys):
                missing.append(field)
        
        # 只有在大部分关键字段都缺失时才报警
        if len(missing) > 0 and len(missing) >= len(spec.target_fields) / 2:
            violations.append(
                ConstraintViolation(
                    kind="missing_fields",
                    severity="warning",
                    summary=f"Potential missing requested fields: {', '.join(missing)}",
                    detail=f"The user requested fields {spec.target_fields}, but available keys in sample item are: {list(item_keys)}.",
                )
            )

    return violations


def enforce_goal_spec_slice(
    data: List[Dict[str, Any]],
    spec: Optional[ScrapeGoalSpec],
) -> List[Dict[str, Any]]:
    """Safe fallback post-processing slicing.
    
    Acts as the final guard gate before exporting data to CSV/JSON/JSONL.
    If the synthesized crawler output all 100 items despite an ordinal/top-k constraint,
    this guard automatically slices the dataset to guarantee 100% semantic compliance.
    """
    if spec is None or not spec.is_constrained() or not data:
        return data

    count = len(data)

    if spec.cardinality == CardinalityMode.ORDINAL and spec.ordinal_index:
        idx = spec.ordinal_index - 1
        if 0 <= idx < count:
            logger.info(
                "Enforcing goal spec slice: Ordinal #%d extracted from %d items",
                spec.ordinal_index,
                count,
            )
            return [data[idx]]
        elif count > 0:
            logger.warning(
                "Ordinal index %d out of bounds for %d items, returning last item as fallback",
                spec.ordinal_index,
                count,
            )
            return [data[-1]]

    elif spec.cardinality == CardinalityMode.TOP_K and spec.limit:
        if count > spec.limit:
            logger.info(
                "Enforcing goal spec slice: Slicing Top %d from %d items",
                spec.limit,
                count,
            )
            return data[:spec.limit]

    elif spec.cardinality == CardinalityMode.SINGLE:
        if count > 1:
            logger.info("Enforcing goal spec slice: Single item sliced from %d items", count)
            return data[:1]

    return data
