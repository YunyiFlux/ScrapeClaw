# -*- coding: utf-8 -*-
"""Jinja2 Production Crawler Synthesizer & Multi-Engine Scaffolding Exporter."""
from pathlib import Path
from typing import Dict, Any

from scrapeclaw.synthesizer.scaffolders import (
    BaseScaffolder,
    HttpxScaffolder,
    DrissionScaffolder,
    ScrapyScaffolder,
    render_scaffold,
)


def render_crawler_script(spec: Dict[str, Any]) -> str:
    """Render single-file httpx asynchronous crawler script (Backward-compatible)."""
    return HttpxScaffolder().render_code(spec)


def render_drission_script(spec: Dict[str, Any]) -> str:
    """Render anti-detection DrissionPage crawler script."""
    return DrissionScaffolder().render_code(spec)


def render_scrapy_project(spec: Dict[str, Any], output_path: Path) -> Dict[str, Path]:
    """Generate industrial multi-file Scrapy project scaffolding."""
    return ScrapyScaffolder().generate(spec, output_path)


__all__ = [
    "render_crawler_script",
    "render_drission_script",
    "render_scrapy_project",
    "render_scaffold",
    "BaseScaffolder",
    "HttpxScaffolder",
    "DrissionScaffolder",
    "ScrapyScaffolder",
]
