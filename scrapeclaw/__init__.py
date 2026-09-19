"""ScrapeClaw: Autonomous SPA Reverse-Engineering & Production Crawler Synthesizer."""

from scrapeclaw.api import AsyncScrapeClaw, ScrapeClaw, synthesize, synthesize_async
from scrapeclaw.exceptions import (
    BrowserLaunchError,
    ConfigurationError,
    ExecutionGateError,
    ReverseEngineeringError,
    ScrapeClawError,
    TargetNavigationError,
)
from scrapeclaw.models import SynthesizedCrawler

__version__ = "1.0.0"

__all__ = [
    "synthesize",
    "synthesize_async",
    "ScrapeClaw",
    "AsyncScrapeClaw",
    "SynthesizedCrawler",
    "ScrapeClawError",
    "ConfigurationError",
    "BrowserLaunchError",
    "TargetNavigationError",
    "ReverseEngineeringError",
    "ExecutionGateError",
    "__version__",
]
