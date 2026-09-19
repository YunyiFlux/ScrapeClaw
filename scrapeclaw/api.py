import asyncio
import concurrent.futures
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from scrapeclaw.config.settings import load_config
from scrapeclaw.engine.llm_client import LLMClient
from scrapeclaw.engine.scope_guard import TargetScopeGuard
from scrapeclaw.engine.solver import AgentSolver
from scrapeclaw.engine.tool_manager import ToolManager
from scrapeclaw.exceptions import (
    BrowserLaunchError,
    ConfigurationError,
    ReverseEngineeringError,
    TargetNavigationError,
)
from scrapeclaw.exporter import get_exporter
from scrapeclaw.models import SynthesizedCrawler
from scrapeclaw.probe.browser import BrowserProbe
from scrapeclaw.traffic.store import TrafficStore


class AsyncScrapeClaw:
    """Asynchronous client for ScrapeClaw reverse-engineering and crawler synthesis."""

    def __init__(
        self,
        *,
        headless: bool = True,
        cdp_url: Optional[str] = None,
        session_file: Optional[str] = None,
        save_session: Optional[str] = None,
        auto_solve_captcha: bool = True,
        hitl_timeout: int = 60,
        allow_cross_domain: bool = False,
        max_steps: int = 25,
        workspace: Optional[str | Path] = None,
        config: Optional[Any] = None,
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
    ):
        self.config = config or load_config()
        self.headless = headless
        self.cdp_url = cdp_url or getattr(self.config.browser, "cdp_url", None)
        self.session_file = session_file
        self.save_session = save_session
        self.auto_solve_captcha = auto_solve_captcha
        self.hitl_timeout = hitl_timeout
        self.allow_cross_domain = allow_cross_domain
        self.max_steps = max_steps
        self.workspace_dir = Path(workspace or "./scrapeclaw_workspace").resolve()

        if llm_api_key:
            self.config.llm.api_key = llm_api_key
        if llm_base_url:
            self.config.llm.base_url = llm_base_url
        if llm_model:
            self.config.llm.model = llm_model

        self.traffic_store: Optional[TrafficStore] = None
        self.browser_probe: Optional[BrowserProbe] = None
        self.llm_client: Optional[LLMClient] = None
        self._is_started = False
        self._current_event_hook: Optional[Callable[[str, dict], None]] = None

    def _on_captcha_event(self, event_type: str, payload: dict):
        if self._current_event_hook:
            self._current_event_hook(event_type, payload)

    async def start(self) -> None:
        if self._is_started:
            return

        if not self.config.llm.api_key:
            raise ConfigurationError(
                "LLM API Key not found. Please set OPENAI_API_KEY/DASHSCOPE_API_KEY or configure .env."
            )

        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.traffic_store = TrafficStore(self.workspace_dir)
        self.browser_probe = BrowserProbe(
            self.traffic_store,
            headless=self.headless,
            cdp_url=self.cdp_url,
            session_file=self.session_file,
            save_session_path=self.save_session,
            auto_solve_captcha=self.auto_solve_captcha,
            hitl_timeout_seconds=self.hitl_timeout,
            on_captcha_event=self._on_captcha_event,
        )
        self.llm_client = LLMClient(self.config.llm)

        try:
            await self.browser_probe.start()
        except Exception as e:
            raise BrowserLaunchError(f"Failed to launch browser probe: {e}") from e

        self._is_started = True

    async def close(self) -> None:
        if self.browser_probe:
            try:
                await self.browser_probe.close()
            except Exception:
                pass
        self._is_started = False

    async def __aenter__(self) -> "AsyncScrapeClaw":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def synthesize(
        self,
        url: str,
        goal: str,
        *,
        engine: str = "httpx",
        output: Optional[str | Path] = None,
        data_output: Optional[str | Path] = None,
        format: Optional[str] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ) -> SynthesizedCrawler:
        if not url or not url.startswith(("http://", "https://")):
            raise TargetNavigationError(f"Invalid target URL: {url}. Must start with http:// or https://")

        engine_clean = (engine or "httpx").lower()
        if engine_clean not in ("httpx", "scrapy", "drission", "drissionpage"):
            raise ConfigurationError(f"Unsupported crawler engine: {engine}. Choose from: httpx, scrapy, drission.")

        auto_started = False
        if not self._is_started:
            await self.start()
            auto_started = True

        self._current_event_hook = on_event

        try:
            if on_event:
                on_event("agent_start", {"target_url": url, "goal": goal, "engine": engine_clean})

            custom_out_file = Path(output) if output else None
            out_dir = custom_out_file.parent if custom_out_file else self.workspace_dir / "output"
            out_dir.mkdir(parents=True, exist_ok=True)

            scope_guard = TargetScopeGuard(url, allow_cross_domain=self.allow_cross_domain)
            tool_manager = ToolManager(
                self.traffic_store,
                self.browser_probe,
                output_dir=out_dir,
                custom_output_file=custom_out_file,
                scope_guard=scope_guard,
                target_engine=engine_clean,
            )

            def internal_event_hook(kind: str, payload: dict):
                if on_event:
                    mapped_kind = "step_thought" if kind == "agent_thought" else kind
                    on_event(mapped_kind, payload)

            solver = AgentSolver(
                self.llm_client,
                tool_manager,
                max_steps=self.max_steps,
                on_event=internal_event_hook,
            )

            t0 = time.time()
            state = await solver.solve(url, goal)
            elapsed = time.time() - t0

            if not state.completed:
                raise ReverseEngineeringError(
                    state.complete_reason or "Autonomous solver budget exhausted without delivering a verified crawler."
                )

            code_text = ""
            sign_text = None
            if state.synthesized_code_path and Path(state.synthesized_code_path).exists():
                p = Path(state.synthesized_code_path)
                if p.is_file():
                    code_text = p.read_text(encoding="utf-8")
                    sign_candidate = p.parent / "sign.js"
                    if sign_candidate.exists():
                        sign_text = sign_candidate.read_text(encoding="utf-8")
                else:
                    code_text = f"# Scrapy project scaffolded at {p}"

            items = state.verified_sample_data or []
            if items:
                from scrapeclaw.engine.constraint_policy import enforce_goal_spec_slice
                items = enforce_goal_spec_slice(items, getattr(state, "goal_spec", None))

            if data_output and items:
                data_path = Path(data_output)
                data_path.parent.mkdir(parents=True, exist_ok=True)
                exporter = get_exporter(format_name=format, file_path=data_path)
                exporter.export(items, data_path)

            target_api = state.get_fact_content("target_api") or state.get_fact_content("target_endpoint")

            crawler = SynthesizedCrawler(
                code=code_text,
                sign_code=sign_text,
                engine=engine_clean,
                target_url=url,
                target_api_url=target_api,
                target_api_method=state.get_fact_content("api_method") or "GET",
                minimal_headers={},
                sample_data=items,
                is_verified=bool(state.completed),
                steps_taken=len(state.tool_calls),
                elapsed_seconds=round(elapsed, 2),
            )

            if output and crawler.code:
                crawler.save(output)

            if on_event:
                on_event("gate_verified", {"passed": crawler.is_verified, "count": len(crawler.sample_data)})

            return crawler
        finally:
            self._current_event_hook = None
            if auto_started:
                await self.close()


class ScrapeClaw:
    """Synchronous client for ScrapeClaw reverse-engineering and crawler synthesis."""

    def __init__(self, **kwargs):
        self._async_client = AsyncScrapeClaw(**kwargs)

    def _run_coro(self, coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(coro)).result()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def start(self) -> None:
        self._run_coro(self._async_client.start())

    def close(self) -> None:
        self._run_coro(self._async_client.close())

    def __enter__(self) -> "ScrapeClaw":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def synthesize(self, url: str, goal: str, **kwargs) -> SynthesizedCrawler:
        return self._run_coro(self._async_client.synthesize(url, goal, **kwargs))


def synthesize(url: str, goal: str, **kwargs) -> SynthesizedCrawler:
    """One-line synchronous entrypoint to synthesize a crawler."""
    client_keys = {
        "headless", "cdp_url", "session_file", "save_session", "auto_solve_captcha",
        "hitl_timeout", "allow_cross_domain", "max_steps", "workspace", "config",
        "llm_api_key", "llm_base_url", "llm_model"
    }
    client_kwargs = {k: v for k, v in kwargs.items() if k in client_keys}
    call_kwargs = {k: v for k, v in kwargs.items() if k not in client_keys}
    with ScrapeClaw(**client_kwargs) as client:
        return client.synthesize(url, goal, **call_kwargs)


async def synthesize_async(url: str, goal: str, **kwargs) -> SynthesizedCrawler:
    """One-line asynchronous entrypoint to synthesize a crawler."""
    client_keys = {
        "headless", "cdp_url", "session_file", "save_session", "auto_solve_captcha",
        "hitl_timeout", "allow_cross_domain", "max_steps", "workspace", "config",
        "llm_api_key", "llm_base_url", "llm_model"
    }
    client_kwargs = {k: v for k, v in kwargs.items() if k in client_keys}
    call_kwargs = {k: v for k, v in kwargs.items() if k not in client_keys}
    async with AsyncScrapeClaw(**client_kwargs) as client:
        return await client.synthesize(url, goal, **call_kwargs)
