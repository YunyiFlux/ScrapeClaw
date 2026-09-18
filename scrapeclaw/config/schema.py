"""ScrapeClaw Configuration Schema."""
from typing import Optional
from pydantic import BaseModel, Field

class LLMConfig(BaseModel):
    provider: str = Field(default="openai", description="LLM provider, e.g. openai, deepseek, qwen")
    api_key: Optional[str] = Field(default=None, description="API Key for the provider")
    base_url: Optional[str] = Field(default="https://api.openai.com/v1", description="API base URL")
    model: str = Field(default="gpt-4o", description="Model name")
    temperature: float = Field(default=0.1, description="Sampling temperature")
    max_tokens: int = Field(default=4096, description="Max output tokens")

class BrowserConfig(BaseModel):
    headless: bool = Field(default=True, description="Run browser probe in headless mode")
    cdp_url: Optional[str] = Field(default=None, description="Remote CDP debug URL, e.g. http://127.0.0.1:9222")
    timeout_seconds: int = Field(default=30, description="Page navigation timeout")
    wait_until: str = Field(default="networkidle", description="Page wait condition")
    auto_solve_captcha: bool = Field(default=True, description="Automatically detect and attempt bypass for captchas/turnstiles")
    hitl_timeout_seconds: int = Field(default=60, description="Human-in-the-loop waiting timeout in seconds")

class SolverConfig(BaseModel):
    max_steps: int = Field(default=30, description="Maximum autonomous steps budget")
    max_tool_rounds: int = Field(default=6, description="Max tool rounds per turn")
    output_dir: str = Field(default="./crawlers", description="Output directory for crawlers")

class SynthesizerConfig(BaseModel):
    target_engine: str = Field(default="httpx", description="Target crawler engine: httpx, scrapy, drission")

class ScrapeClawConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    synthesizer: SynthesizerConfig = Field(default_factory=SynthesizerConfig)
