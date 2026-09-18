"""ScrapeClaw Configuration Loader."""
import os
from pathlib import Path
from typing import Optional
import yaml
from dotenv import load_dotenv
from scrapeclaw.config.schema import ScrapeClawConfig

# Auto load .env from current directory or parent directories
load_dotenv()

GLOBAL_CONFIG_PATH = Path.home() / ".scrapeclaw" / "config.yaml"
LOCAL_CONFIG_PATHS = [
    Path("scrapeclaw.yaml"),
    Path("config.yaml"),
    Path(".scrapeclaw.yaml"),
]

def load_config(custom_path: Optional[Path] = None) -> ScrapeClawConfig:
    data = {}
    config_file = None

    if custom_path and custom_path.exists():
        config_file = custom_path
    else:
        # Check local paths first
        for local_p in LOCAL_CONFIG_PATHS:
            if local_p.exists():
                config_file = local_p
                break
        # Fallback to global config
        if not config_file and GLOBAL_CONFIG_PATH.exists():
            config_file = GLOBAL_CONFIG_PATH

    if config_file and config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            pass

    config = ScrapeClawConfig.model_validate(data)

    # Environment variables override (supports standard OPENAI_* and SCRAPECLAW_*)
    api_key = os.getenv("SCRAPECLAW_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if api_key:
        config.llm.api_key = api_key

    base_url = os.getenv("SCRAPECLAW_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if base_url:
        config.llm.base_url = base_url

    model = os.getenv("SCRAPECLAW_LLM_MODEL") or os.getenv("OPENAI_MODEL") or os.getenv("MODEL_NAME")
    if model:
        config.llm.model = model

    provider = os.getenv("SCRAPECLAW_LLM_PROVIDER")
    if provider:
        config.llm.provider = provider

    return config
