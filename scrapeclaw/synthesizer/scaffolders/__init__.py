# -*- coding: utf-8 -*-
"""Scaffolders package for ScrapeClaw multi-engine code synthesis."""
from pathlib import Path
from typing import Dict, Any
from scrapeclaw.synthesizer.scaffolders.base import BaseScaffolder
from scrapeclaw.synthesizer.scaffolders.httpx_scaffolder import HttpxScaffolder
from scrapeclaw.synthesizer.scaffolders.drission_scaffolder import DrissionScaffolder
from scrapeclaw.synthesizer.scaffolders.scrapy_scaffolder import ScrapyScaffolder
from scrapeclaw.synthesizer.scaffolders.playwright_scaffolder import PlaywrightScaffolder


def render_scaffold(spec: Dict[str, Any], engine: str = "httpx", output_path: Path = None) -> Dict[str, Path]:
    """Factory function to render crawler code or project structure based on engine."""
    engine = (engine or "httpx").lower()
    if output_path is None:
        output_path = Path("./generated_spider.py")

    if engine == "scrapy":
        scaffolder = ScrapyScaffolder()
    elif engine in ("drission", "drissionpage"):
        scaffolder = DrissionScaffolder()
    elif engine in ("playwright", "playwright-dom", "dom"):
        scaffolder = PlaywrightScaffolder()
    else:
        scaffolder = HttpxScaffolder()

    return scaffolder.generate(spec, output_path)


__all__ = [
    "BaseScaffolder",
    "HttpxScaffolder",
    "DrissionScaffolder",
    "ScrapyScaffolder",
    "PlaywrightScaffolder",
    "render_scaffold",
]
