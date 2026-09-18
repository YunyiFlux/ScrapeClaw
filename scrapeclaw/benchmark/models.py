# -*- coding: utf-8 -*-
"""ScrapeEval-50 Benchmark Domain Models and Reporting Structures."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional
import json


class BenchmarkCategory(str, Enum):
    PAGINATION = "pagination"
    NAVIGATION = "navigation"
    UNPACKING = "unpacking"
    AUTH_SESSION = "auth_session"
    ANTI_SCRAPING = "anti_scraping"
    CAPTCHA = "captcha"
    SCAFFOLDING = "scaffolding"


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass
class BenchmarkTask:
    id: str
    name: str
    category: BenchmarkCategory
    difficulty: DifficultyLevel
    endpoint_path: str
    goal: str
    expected_fields: List[str]
    min_pass_items: int = 1
    target_cardinality: Optional[str] = None
    description: str = ""

    def get_full_url(self, base_url: str) -> str:
        base = base_url.rstrip("/")
        path = self.endpoint_path.lstrip("/")
        return f"{base}/{path}"


@dataclass
class TaskResult:
    task_id: str
    task_name: str
    category: str
    difficulty: str
    passed: bool
    steps: int
    duration_seconds: float
    extracted_count: int
    error_message: str = ""
    synthesized_engine: str = "httpx"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CategorySummary:
    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    avg_steps: float = 0.0
    avg_duration: float = 0.0


@dataclass
class BenchmarkReport:
    total_tasks: int = 0
    passed_tasks: int = 0
    pass_rate: float = 0.0
    avg_steps: float = 0.0
    avg_duration: float = 0.0
    categories: Dict[str, CategorySummary] = field(default_factory=dict)
    results: List[TaskResult] = field(default_factory=list)

    @classmethod
    def compute(cls, results: List[TaskResult]) -> "BenchmarkReport":
        total = len(results)
        if total == 0:
            return cls()

        passed = sum(1 for r in results if r.passed)
        avg_steps = sum(r.steps for r in results) / total
        avg_duration = sum(r.duration_seconds for r in results) / total

        # Group by category
        cat_groups: Dict[str, List[TaskResult]] = {}
        for r in results:
            cat_groups.setdefault(r.category, []).append(r)

        cat_summaries: Dict[str, CategorySummary] = {}
        for cat, cat_res in cat_groups.items():
            cat_total = len(cat_res)
            cat_passed = sum(1 for cr in cat_res if cr.passed)
            cat_summaries[cat] = CategorySummary(
                total=cat_total,
                passed=cat_passed,
                pass_rate=round(cat_passed / cat_total, 3) if cat_total > 0 else 0.0,
                avg_steps=round(sum(cr.steps for cr in cat_res) / cat_total, 1),
                avg_duration=round(sum(cr.duration_seconds for cr in cat_res) / cat_total, 2),
            )

        return cls(
            total_tasks=total,
            passed_tasks=passed,
            pass_rate=round(passed / total, 3),
            avg_steps=round(avg_steps, 1),
            avg_duration=round(avg_duration, 2),
            categories=cat_summaries,
            results=results,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "passed_tasks": self.passed_tasks,
            "pass_rate": self.pass_rate,
            "avg_steps": self.avg_steps,
            "avg_duration": self.avg_duration,
            "categories": {k: asdict(v) for k, v in self.categories.items()},
            "results": [r.to_dict() for r in self.results],
        }

    def save_json(self, output_file: Path) -> None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
