"""AgentState & Dual-Tier Memory System for Autonomous Agent."""
from datetime import datetime
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field
from scrapeclaw.core.goal_spec import ScrapeGoalSpec
from scrapeclaw.analyzer.goal_parser import parse_goal_spec
from scrapeclaw.engine.planner import ExecutionPlan, ScrapePhase, build_execution_plan

class PinnedFact(BaseModel):
    fact_type: str
    content: str
    traffic_id: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class EvidenceRecord(BaseModel):
    id: str
    source_tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str
    raw_content: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    ok: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class AgentState(BaseModel):
    target_url: str = ""
    goal_description: str = ""
    goal_spec: ScrapeGoalSpec = Field(default_factory=lambda: ScrapeGoalSpec(raw_goal=""))
    execution_plan: ExecutionPlan = Field(default_factory=ExecutionPlan)

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if self.goal_description and (not self.goal_spec or not self.goal_spec.raw_goal):
            self.goal_spec = parse_goal_spec(self.goal_description)
        if not self.execution_plan.steps:
            self.execution_plan = build_execution_plan(self.target_url, self.goal_spec)

    def set_goal(self, goal: str) -> None:
        self.goal_description = goal
        self.goal_spec = parse_goal_spec(goal)
        self.execution_plan = build_execution_plan(self.target_url, self.goal_spec)
    pinned_facts: List[PinnedFact] = Field(default_factory=list)
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    correction_hints: List[str] = Field(default_factory=list)
    completed: bool = False
    complete_reason: str = ""
    synthesized_code_path: str = ""
    verification_passed: bool = False
    verified_sample_data: List[Dict[str, Any]] = Field(default_factory=list)
    captcha_challenges_resolved: int = 0
    has_auth_session: bool = False
    evidence_seq: int = Field(default=0, exclude=True)

    def has_fact_type(self, fact_type: str) -> bool:
        return any(f.fact_type == fact_type for f in self.pinned_facts)

    def get_fact_content(self, fact_type: str) -> Optional[str]:
        for f in self.pinned_facts:
            if f.fact_type == fact_type:
                return f.content
        return None

    def pin_fact(self, fact_type: str, content: str, traffic_id: str = ""):
        if not any(f.content == content for f in self.pinned_facts):
            self.pinned_facts.append(PinnedFact(fact_type=fact_type, content=content, traffic_id=traffic_id))

    def add_correction_hint(self, hint: str):
        if hint not in self.correction_hints:
            self.correction_hints.append(hint)
            self.correction_hints = self.correction_hints[-6:]

    def record_evidence(self, tool: str, arguments: dict, summary: str, raw: str) -> EvidenceRecord:
        self.evidence_seq += 1
        rec = EvidenceRecord(
            id=f"e{self.evidence_seq:03d}",
            source_tool=tool,
            arguments=arguments,
            summary=summary,
            raw_content=raw
        )
        self.evidence.append(rec)
        return rec

    def to_prompt_summary(self) -> str:
        lines = [
            f"Target URL: {self.target_url}",
            f"Extraction Goal: {self.goal_description}",
        ]
        if self.pinned_facts:
            lines.append("\nPinned Facts (Confirmed Knowledge):")
            for f in self.pinned_facts[-8:]:
                lines.append(f"- [{f.fact_type}] {f.content}" + (f" (ref: {f.traffic_id})" if f.traffic_id else ""))
        if self.correction_hints:
            lines.append("\nDiagnostic Notes & Guards:")
            for h in self.correction_hints[-4:]:
                lines.append(f"- {h}")
        if self.execution_plan and self.execution_plan.steps:
            lines.append("\n" + self.execution_plan.to_prompt_block())
        if self.evidence:
            lines.append("\nRecent Evidence:")
            for e in self.evidence[-6:]:
                lines.append(f"- {e.id}: [{e.source_tool}] {e.summary}")
        return "\n".join(lines)
