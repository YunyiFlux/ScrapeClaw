"""Domain models for target goals, semantic constraints, and cardinality.

Structured TaskConstraints domain model.
Separates general agent persona from dynamic, per-task structured constraints.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class CardinalityMode(str, Enum):
    """Extraction cardinality mode specified by the user."""
    ALL = "all"            # Extract all available list items (default)
    ORDINAL = "ordinal"    # Extract exact single ordinal item (e.g. 2nd item only)
    TOP_K = "top_k"        # Extract first K items (e.g. top 5)
    SINGLE = "single"      # Extract a single superlative item (e.g. latest, highest)


class ScrapeGoalSpec(BaseModel):
    """Structured goal specification and constraints for a crawling task.
    
    Parsed from natural language by GoalParser and used throughout the agent loop:
    1. Dynamic prompt context injection (to_prompt_block)
    2. Sandbox verification constraint auditing (validate_extracted_data)
    3. Exporter output fallback slicing (enforce_goal_spec_slice)
    """
    raw_goal: str = Field(default="", description="Original natural language goal")
    cardinality: CardinalityMode = Field(
        default=CardinalityMode.ALL,
        description="Cardinality requirement of extraction results",
    )
    ordinal_index: Optional[int] = Field(
        default=None,
        description="1-based ordinal position if cardinality is ORDINAL (e.g., 2 for second)",
    )
    limit: Optional[int] = Field(
        default=None,
        description="Maximum number of items if TOP_K or SINGLE",
    )
    sort_metric: Optional[str] = Field(
        default=None,
        description="Attribute or metric name to sort by (e.g., view_count, date, price)",
    )
    sort_order: Optional[str] = Field(
        default="desc",
        description="Sort direction: 'desc' or 'asc'",
    )
    filter_keywords: List[str] = Field(
        default_factory=list,
        description="Categories, tags, or search keywords to filter by before ranking",
    )
    target_fields: List[str] = Field(
        default_factory=list,
        description="Target field names explicitly requested (e.g. title, up_name, etc.)",
    )
    strict_mode: bool = Field(
        default=True,
        description="When True, enforce exact cardinality slicing and strict validation",
    )

    def is_constrained(self) -> bool:
        """Return True if this task has specific cardinality, sorting, or filtering constraints."""
        return (
            self.cardinality != CardinalityMode.ALL
            or bool(self.filter_keywords)
            or bool(self.sort_metric)
            or bool(self.target_fields)
        )

    def to_prompt_block(self) -> str:
        """Render constraints into a dynamic, structured prompt block for agent execution rounds.
        
        Constructs dynamic prompt block for task constraints.
        Keeps base SYSTEM_PROMPT clean and generic, while injecting runtime task constraints.
        """
        if not self.is_constrained():
            return ""

        lines = ["## 当前任务目标规格与切片约束 (Task-Specific Constraints)"]
        
        # 1. 过滤约束
        if self.filter_keywords:
            lines.append(
                f"- 【分类与过滤约束】抓取数据前必须确保仅包含符合分类/关键词: {', '.join(self.filter_keywords)} 的项目。"
            )

        # 2. 排序约束
        if self.sort_metric:
            order_desc = "从大到小 (降序)" if self.sort_order == "desc" else "从小到大 (升序)"
            lines.append(
                f"- 【排序依据】数据必须先按 '{self.sort_metric}' 进行 {order_desc} 排序。"
            )

        # 3. 数量与基数约束
        if self.cardinality == CardinalityMode.ORDINAL and self.ordinal_index:
            lines.append(
                f"- 【严格单条序数约束】用户指定提取第 {self.ordinal_index} 项数据！"
                f"最终输出数组 `output_data` 必须且仅包含排序后的该 1 条记录（例如 `output_data = [sorted_items[{self.ordinal_index - 1}]]`）。"
                f"禁止输出包含全量 100 条或其他多余记录的列表！"
            )
        elif self.cardinality == CardinalityMode.TOP_K and self.limit:
            lines.append(
                f"- 【Top-K 截断约束】用户指定提取前 {self.limit} 条数据！"
                f"最终输出数组 `output_data` 必须切片为至多 {self.limit} 条记录（例如 `output_data = sorted_items[:{self.limit}]`）。"
            )
        elif self.cardinality == CardinalityMode.SINGLE:
            lines.append(
                "- 【极值单条约束】用户指定提取符合条件的单一极值记录（最高/最新等），最终输出数组长度必须为 1。"
            )

        # 4. 字段提示
        if self.target_fields:
            lines.append(
                f"- 【目标字段】提取结果必须包含以下字段: {', '.join(self.target_fields)}。"
            )

        return "\n".join(lines)
