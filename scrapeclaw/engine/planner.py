"""Execution Planning & Phased Task Decomposition for ScrapeClaw.

Goal-directed planner and navigation phase controller.
Enforces structured multi-step planning and prevents agent from skipping category
navigation / view alignment interactions when the user goal specifies a sub-category.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from scrapeclaw.core.goal_spec import ScrapeGoalSpec


class ScrapePhase(str, Enum):
    """Lifecycle phases for an autonomous crawling synthesis task."""
    DISCOVERY = "discovery"             # Initial page load and structure analysis
    VIEW_ALIGNMENT = "view_alignment"   # Category navigation, tab clicking, view switching
    API_REVERSE = "api_reverse"         # Inspecting private JSON APIs & minimal headers
    SYNTHESIS = "synthesis"             # Code generation (standard or custom crawler)
    VERIFICATION = "verification"       # Sandbox execution & semantic purity auditing


class PlanStep(BaseModel):
    """A discrete sub-task step in the execution plan."""
    id: int
    phase: ScrapePhase
    title: str
    description: str
    status: str = "pending"  # "pending", "active", "completed", "skipped"
    required: bool = True

    def mark_active(self) -> None:
        self.status = "active"

    def mark_completed(self) -> None:
        self.status = "completed"

    def mark_skipped(self) -> None:
        self.status = "skipped"


class ExecutionPlan(BaseModel):
    """Structured execution plan for the current crawling task."""
    steps: List[PlanStep] = Field(default_factory=list)
    current_step_id: int = 1
    requires_view_alignment: bool = False

    def get_current_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.id == self.current_step_id:
                return step
        return None

    def advance_to_phase(self, phase: ScrapePhase) -> None:
        """Advance the plan when a phase is reached or completed."""
        target_id = None
        for step in self.steps:
            if step.phase == phase:
                target_id = step.id
                break
        if target_id is not None:
            self.current_step_id = target_id
            for step in self.steps:
                if step.id < target_id:
                    step.mark_completed()
                elif step.id == target_id:
                    step.mark_active()

    def complete_step(self, step_id: int) -> None:
        for step in self.steps:
            if step.id == step_id:
                step.mark_completed()
        # Advance current_step_id to next pending
        for step in self.steps:
            if step.status == "pending":
                step.mark_active()
                self.current_step_id = step.id
                break

    def is_alignment_completed(self) -> bool:
        """Return True if view alignment is either not required or already completed."""
        if not self.requires_view_alignment:
            return True
        for step in self.steps:
            if step.phase == ScrapePhase.VIEW_ALIGNMENT:
                return step.status == "completed"
        return True

    def to_prompt_block(self) -> str:
        """Render the structured execution plan into a prompt section for LLM decision rounds."""
        if not self.steps:
            return ""

        lines = ["## 🎯 任务拆解与执行阶段计划 (Execution Plan & Progress)"]
        for step in self.steps:
            if step.status == "completed":
                icon = "✅"
            elif step.status == "active":
                icon = "👉 [当前步骤 ACTIVE]"
            elif step.status == "skipped":
                icon = "⏭️"
            else:
                icon = "⏳ [待执行 PENDING]"

            req_mark = " (必须完成，不可跳过)" if step.required else ""
            lines.append(f"{step.id}. {icon} 【{step.phase.value.upper()}】{step.title}{req_mark}")
            lines.append(f"   说明: {step.description}")

        lines.append(
            "\n💡 核心执行原则: 必须按序推进。若当前步骤为 VIEW_ALIGNMENT，严禁在未完成分类交互前直接合成代码！"
        )
        return "\n".join(lines)


def build_execution_plan(target_url: str, goal_spec: Optional[ScrapeGoalSpec] = None) -> ExecutionPlan:
    """Build a tailored execution plan based on target URL and goal specification.
    
    If the goal specifies a sub-category or filtering keyword (e.g. '科技数码', '游戏'),
    and the target URL is a broad/general URL (e.g. /v/popular/all or homepage),
    a mandatory VIEW_ALIGNMENT step is injected between DISCOVERY and API_REVERSE.
    """
    steps: List[PlanStep] = []
    has_category = bool(goal_spec and goal_spec.filter_keywords)
    
    # Check if target URL already explicitly targets the category
    url_lower = (target_url or "").lower()
    url_already_scoped = False
    if has_category and goal_spec:
        for kw in goal_spec.filter_keywords:
            if kw.lower() in url_lower:
                url_already_scoped = True
                break

    step_id = 1
    # Step 1: Initial Discovery
    steps.append(
        PlanStep(
            id=step_id,
            phase=ScrapePhase.DISCOVERY,
            title="页面初探与结构感知 (Initial Page Probe)",
            description=f"加载目标页面 {target_url}，分析页面布局与导航栏结构。",
            status="active",
            required=True,
        )
    )
    step_id += 1

    # Step 2: View Alignment (if category filtering is specified)
    requires_alignment = has_category and not url_already_scoped
    if requires_alignment and goal_spec:
        category_str = ", ".join(goal_spec.filter_keywords)
        steps.append(
            PlanStep(
                id=step_id,
                phase=ScrapePhase.VIEW_ALIGNMENT,
                title=f"分类栏目导航与交互切换 (Category View Alignment: '{category_str}')",
                description=(
                    f"用户目标明确要求【{category_str}】分类！当前页面为综合大盘视图。"
                    f"必须使用 browser_inspect_dom 查找与【{category_str}】匹配的 Tab/导航栏目，"
                    f"并调用 browser_click 点击对应分类栏目，切换视图并捕获专属分类 API！"
                    f"禁止在综合大盘数据流中粗暴过滤！"
                ),
                status="pending",
                required=True,
            )
        )
        step_id += 1

    # Step 3: API Reverse Engineering
    steps.append(
        PlanStep(
            id=step_id,
            phase=ScrapePhase.API_REVERSE,
            title="专用数据源 API 逆向分析 (Dedicated API Reverse-Engineering)",
            description="在目标视图下捕获并分析专用的数据 JSON API，精简请求头与参数。",
            status="pending",
            required=True,
        )
    )
    step_id += 1

    # Step 4: Crawler Synthesis
    steps.append(
        PlanStep(
            id=step_id,
            phase=ScrapePhase.SYNTHESIS,
            title="独立爬虫代码合成 (Crawler Synthesis)",
            description="基于专属 API 编写纯 Python 高性能独立爬虫脚本（支持 CLI 参数与 UTF-8 输出）。",
            status="pending",
            required=True,
        )
    )
    step_id += 1

    # Step 5: Verification & Audit
    steps.append(
        PlanStep(
            id=step_id,
            phase=ScrapePhase.VERIFICATION,
            title="沙箱物理验证与分类纯度审计 (Sandbox Verification & Purity Audit)",
            description="在离线沙箱中运行爬虫脚本，确保 exit_code==0 且提取结果 100% 纯净符合目标分类与基数要求。",
            status="pending",
            required=True,
        )
    )

    return ExecutionPlan(
        steps=steps,
        current_step_id=1,
        requires_view_alignment=requires_alignment,
    )
