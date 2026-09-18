import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

"""ScrapeClaw CLI Entrypoint."""
import asyncio
import json
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from scrapeclaw.config.settings import load_config
from scrapeclaw.traffic.store import TrafficStore
from scrapeclaw.probe.browser import BrowserProbe
from scrapeclaw.engine.llm_client import LLMClient
from scrapeclaw.engine.tool_manager import ToolManager
from scrapeclaw.engine.solver import AgentSolver
from scrapeclaw.exporter import get_exporter
from scrapeclaw.engine.scope_guard import TargetScopeGuard

app = typer.Typer(help="ScrapeClaw - Autonomous SPA Reverse-Engineering & Crawler Synthesizer Agent")
console = Console()

@app.command("run")
def run(
    target_pos: Optional[str] = typer.Argument(None, help="Target SPA webpage URL (positional argument)"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Target SPA webpage URL"),
    goal: str = typer.Option(..., "--goal", "-g", help="Natural language extraction goal"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Path to save synthesized crawler script"),
    data_output: Optional[str] = typer.Option(None, "--data-output", "-d", help="Path to save extracted data file"),
    format: Optional[str] = typer.Option(None, "--format", "-f", help="Data export format: json, jsonl, csv (default: auto-deduced from output file extension)"),
    target_engine: str = typer.Option("httpx", "--target-engine", "-e", help="Target crawler engine: httpx (single-file), scrapy (industrial project), drission (anti-detection)"),
    session_file: Optional[str] = typer.Option(None, "--session-file", "-s", help="Path to external session file or raw cookie string"),
    save_session: Optional[str] = typer.Option(None, "--save-session", help="Path to save exported session credentials upon completion"),
    allow_cross_domain: bool = typer.Option(False, "--allow-cross-domain", help="Allow browser probe to navigate out of target root domain"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser probe in headless mode"),
    browser_url: Optional[str] = typer.Option(None, "--browser-url", help="Attach to existing Chrome via CDP"),
    auto_solve_captcha: bool = typer.Option(True, "--auto-solve-captcha/--no-auto-solve-captcha", help="Automatically detect and attempt bypass for captchas/turnstiles"),
    hitl_timeout: int = typer.Option(60, "--hitl-timeout", help="Human-in-the-loop challenge waiting timeout in seconds"),
    max_steps: int = typer.Option(25, "--max-steps", help="Max autonomous exploration steps"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Override LLM API Key"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Override LLM Base URL"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override LLM Model name"),
):
    """Run autonomous reverse-engineering and synthesize standalone crawler."""
    target_url = url or target_pos
    if not target_url:
        console.print("[bold red]Error:[/bold red] Target URL is required. Provide it as positional argument or via --url.")
        raise typer.Exit(code=1)

    config = load_config()
    if browser_url:
        config.browser.cdp_url = browser_url
    config.browser.headless = headless
    if api_key:
        config.llm.api_key = api_key
    if base_url:
        config.llm.base_url = base_url
    if model:
        config.llm.model = model

    if not config.llm.api_key:
        msg = (
            "[bold yellow]LLM API Key not found![/bold yellow]\n\n"
            "Please configure your API Key using one of the following methods:\n"
            "1. Create a [bold cyan].env[/bold cyan] file in project root:\n"
            "   [green]OPENAI_API_KEY=sk-xxxx[/green]\n"
            "   [green]OPENAI_BASE_URL=https://api.openai.com/v1[/green] (optional)\n\n"
            "2. Pass directly in CLI:\n"
            "   [green]python -m scrapeclaw run --url \"...\" --goal \"...\" --api-key sk-xxxx[/green]\n\n"
            "3. Set terminal environment variable:\n"
            "   [green]$env:OPENAI_API_KEY='sk-xxxx'[/green]"
        )
        console.print(Panel(msg, title="Configuration Notice"))
        raise typer.Exit(code=1)

    workspace = Path("./scrapeclaw_workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    
    custom_out_file = Path(output) if output else None
    out_dir = custom_out_file.parent if custom_out_file else Path(config.solver.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    engine_clean = (target_engine or "httpx").lower()
    if engine_clean not in ("httpx", "scrapy", "drission", "drissionpage"):
        console.print(f"[bold red]Error:[/bold red] Unsupported engine '{target_engine}'. Choose from: httpx, scrapy, drission.")
        raise typer.Exit(code=1)

    header_info = (
        f"[bold cyan]ScrapeClaw Agent Initializing[/bold cyan]\n"
        f"[green]Target:[/green] {target_url}\n"
        f"[green]Goal:[/green] {goal}\n"
        f"[green]Engine:[/green] {engine_clean}\n"
        f"[green]Model:[/green] {config.llm.model} ({config.llm.base_url})\n"
        f"[green]Output:[/green] {output or str(out_dir / ('scrapeclaw_project' if engine_clean == 'scrapy' else 'generated_spider.py'))}\n"
        f"[green]Scope Guard:[/green] {'Permissive (cross-domain allowed)' if allow_cross_domain else 'Locked to target root domain'}"
    )
    console.print(Panel(header_info, title="ScrapeClaw"))

    traffic_store = TrafficStore(workspace)

    def on_captcha_event(event_type: str, payload: dict):
        if event_type == "captcha_detected":
            chal = payload.get("challenge")
            path = payload.get("screenshot_path", "")
            desc = chal.details if chal else ""
            ctype = chal.challenge_type.value if chal else "unknown"
            hint = ""
            if config.browser.headless:
                hint = "\n[dim yellow]💡 提示: 浏览器处于无头模式(Headless)。若遇复杂人机验证需手动操作，建议追加 '--no-headless' 参数启动实机窗口。[/dim yellow]"
            msg = (
                f"[bold red]⚠️  Bot Challenge Detected![/bold red]\n"
                f"[yellow]Type:[/yellow] {ctype}\n"
                f"[yellow]Details:[/yellow] {desc}\n"
                f"[yellow]Screenshot:[/yellow] {path}\n"
                f"[cyan]Waiting for auto-bypass or human-in-the-loop resolution...[/cyan]{hint}"
            )
            console.print(Panel(msg, title="[bold red]Anti-Bot Security Challenge[/bold red]"))
        elif event_type == "captcha_resolved":
            chal = payload.get("challenge")
            ctype = chal.challenge_type.value if chal else "unknown"
            console.print(f"[bold green]✓ Captcha Challenge Resolved ({ctype})! Resuming exploration...[/bold green]")
        elif event_type == "captcha_failed":
            chal = payload.get("challenge")
            ctype = chal.challenge_type.value if chal else "unknown"
            console.print(f"[bold red]❌ Captcha Challenge Resolution Failed or Timed Out ({ctype}).[/bold red]")

    browser_probe = BrowserProbe(
        traffic_store,
        headless=config.browser.headless,
        cdp_url=config.browser.cdp_url,
        session_file=session_file,
        save_session_path=save_session,
        auto_solve_captcha=auto_solve_captcha,
        hitl_timeout_seconds=hitl_timeout,
        on_captcha_event=on_captcha_event,
        target_url=target_url,
    )
    if session_file:
        console.print(f"[bold cyan]🔑 Session Loaded:[/bold cyan] {session_file} (Bound to domain: {browser_probe.target_domain})")
    llm_client = LLMClient(config.llm)
    scope_guard = TargetScopeGuard(target_url, allow_cross_domain=allow_cross_domain)
    tool_manager = ToolManager(
        traffic_store,
        browser_probe,
        output_dir=out_dir,
        custom_output_file=custom_out_file,
        scope_guard=scope_guard,
        target_engine=engine_clean,
    )

    def on_event(kind: str, payload: dict):
        if kind == "step_start":
            console.print(f"\n[bold blue]-- Round {payload['step']} --[/bold blue]")
        elif kind == "agent_thought":
            console.print(f"[dim]{payload['thought']}[/dim]")
        elif kind == "tool_call":
            console.print(f"[yellow][Tool Call][/yellow] [bold]{payload['tool']}[/bold]")
        elif kind == "tool_result":
            console.print(f"[green][Tool Result][/green] {payload['summary']}")
        elif kind == "completed":
            console.print(f"\n[bold green][SUCCESS][/bold green] {payload['reason']}")

    solver = AgentSolver(llm_client, tool_manager, max_steps=max_steps, on_event=on_event)

    async def _async_run():
        await browser_probe.start()
        try:
            state = await solver.solve(target_url, goal)
            if state.completed:
                if data_output:
                    data_file = Path(data_output)
                elif custom_out_file:
                    data_file = custom_out_file.parent / f"{custom_out_file.stem}_data.json"
                else:
                    data_file = out_dir / "extracted_data.json"

                data_file.parent.mkdir(parents=True, exist_ok=True)
                items = state.verified_sample_data or []
                if items:
                    from scrapeclaw.engine.constraint_policy import enforce_goal_spec_slice
                    items = enforce_goal_spec_slice(items, getattr(state, "goal_spec", None))
                    exporter = get_exporter(format_name=format, file_path=data_file)
                    exporter.export(items, data_file)

                if items:
                    first_item = items[0]
                    keys = list(first_item.keys())[:5]
                    preview_count = min(len(items), 5)
                    
                    table = Table(
                        title=f"🎉 目标数据提取成果预览 (展示前 {preview_count} 条 / 共 {len(items)} 条)",
                        border_style="cyan",
                        header_style="bold magenta"
                    )
                    for k in keys:
                        table.add_column(
                            str(k),
                            style="bold yellow" if k in ("title", "name", "id") else "white",
                            overflow="fold"
                        )

                    for item in items[:preview_count]:
                        row_vals = []
                        for k in keys:
                            val = str(item.get(k, ""))
                            if len(val) > 70:
                                val = val[:67] + "..."
                            row_vals.append(val)
                        table.add_row(*row_vals)

                    console.print("\n")
                    console.print(table)
                    console.print(f"\n[bold green]✔ 完整提取数据已落盘保存至:[/bold green] [cyan]{data_file.resolve()}[/cyan] ({len(items)} items)")
                    console.print(f"[bold green]✔ 独立离线爬虫脚本已保存至:[/bold green] [cyan]{state.synthesized_code_path}[/cyan]\n")

                pass_summary = (
                    f"[bold green]Crawler Delivered & Physical Verification Passed![/bold green]\n\n"
                    f"[cyan]Target URL:[/cyan] {target_url}\n"
                    f"[cyan]Extraction Goal:[/cyan] {goal}\n"
                    f"[cyan]Items Extracted:[/cyan] {len(items)} records\n"
                    f"[cyan]Crawler Script:[/cyan] {state.synthesized_code_path}\n"
                    f"[cyan]Saved Data File:[/cyan] {data_file.resolve()}\n\n"
                    f"[dim]Run offline crawler directly anytime: [bold green]python {state.synthesized_code_path}[/bold green][/dim]"
                )
                console.print(Panel(pass_summary, title="Execution Gate Passed", border_style="green"))
            else:
                console.print(Panel("[bold red]Solve loop budget exhausted without verified crawler.[/bold red]", title="Incomplete", border_style="red"))
        finally:
            await browser_probe.close()

    asyncio.run(_async_run())

@app.command("version")
def version():
    console.print("ScrapeClaw v1.0.0")



@app.command("bench")
def bench(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter tasks by category: pagination, navigation, unpacking, auth_session, anti_scraping, captcha, scaffolding"),
    max_tasks: Optional[int] = typer.Option(None, "--max-tasks", "-n", help="Max number of benchmark tasks to run"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Path to save benchmark JSON report"),
):
    """Run ScrapeEval-50 automated benchmark matrix and evaluate agent capabilities."""
    from scrapeclaw.benchmark.harness import BenchmarkHarness

    header = (
        "[bold cyan]ScrapeEval-50 Comprehensive Benchmark Matrix[/bold cyan]\n"
        f"[green]Category Filter:[/green] {category or 'All 7 Categories'}\n"
        f"[green]Task Limit:[/green] {max_tasks or 'All Selected'}\n"
        f"[green]Report Output:[/green] {output or 'Console Only'}"
    )
    console.print(Panel(header, title="ScrapeClaw Benchmark"))

    harness = BenchmarkHarness(category=category, max_tasks=max_tasks)
    selected_tasks = harness.get_selected_tasks()
    console.print(f"[bold]Executing {len(selected_tasks)} benchmark evaluation tasks...[/bold]\n")

    report = asyncio.run(harness.run())

    # 1. Render Category Breakdown Table
    cat_table = Table(title="[bold green]ScrapeEval-50 Category Scorecard[/bold green]")
    cat_table.add_column("Category", style="cyan", no_wrap=True)
    cat_table.add_column("Total", justify="right", style="white")
    cat_table.add_column("Passed", justify="right", style="green")
    cat_table.add_column("Pass Rate", justify="right", style="bold yellow")
    cat_table.add_column("Avg Steps", justify="right", style="magenta")
    cat_table.add_column("Avg Duration", justify="right", style="blue")

    for cat_name, sum_data in report.categories.items():
        pct = f"{sum_data.pass_rate * 100:.1f}%"
        cat_table.add_row(
            cat_name,
            str(sum_data.total),
            str(sum_data.passed),
            pct,
            f"{sum_data.avg_steps:.1f}",
            f"{sum_data.avg_duration:.2f}s",
        )
    console.print(cat_table)

    # 2. Render Overall Summary Card
    overall_pct = f"{report.pass_rate * 100:.1f}%"
    summary_text = (
        f"[bold]Total Tasks Evaluated:[/bold] {report.total_tasks}\n"
        f"[bold]Passed Tasks:[/bold] [green]{report.passed_tasks}[/green] / {report.total_tasks}\n"
        f"[bold]Overall Pass@1 Success Rate:[/bold] [bold green]{overall_pct}[/bold green]\n"
        f"[bold]Average Exploration Steps:[/bold] {report.avg_steps:.1f} steps\n"
        f"[bold]Average Duration per Task:[/bold] {report.avg_duration:.2f}s"
    )
    console.print(Panel(summary_text, title="[bold green]Benchmark Summary Results[/bold green]"))

    if output:
        out_path = Path(output)
        report.save_json(out_path)
        console.print(f"[bold green]Saved benchmark JSON report to {out_path}[/bold green]")


@app.command("doctor")
def doctor():
    """Run environment diagnostics to verify system readiness (Python, Playwright, Node.js, LLM)."""
    import os
    import sys
    import shutil
    import subprocess
    from rich.table import Table

    table = Table(title="[bold cyan]ScrapeClaw Environment Doctor[/bold cyan]")
    table.add_column("Component", style="bold white")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="cyan")
    table.add_column("Action / Recommendation", style="yellow")

    all_good = True

    # 1. Python Check
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        table.add_row("Python", "[bold green]PASS[/bold green]", f"v{py_ver} (>= 3.10)", "[green]Ready[/green]")
    else:
        table.add_row("Python", "[bold red]FAIL[/bold red]", f"v{py_ver} (< 3.10)", "Upgrade Python to >= 3.10")
        all_good = False

    # 2. Playwright Chromium Browser Check
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            chromium_path = pw.chromium.executable_path
            if os.path.exists(chromium_path):
                table.add_row("Playwright Chromium", "[bold green]PASS[/bold green]", "Browser installed & ready", "[green]Ready[/green]")
            else:
                table.add_row("Playwright Chromium", "[bold yellow]WARN[/bold yellow]", "Chromium binary not detected", "Run: playwright install chromium")
                all_good = False
    except Exception as e:
        table.add_row("Playwright Chromium", "[bold yellow]WARN[/bold yellow]", f"Check error: {str(e)[:40]}", "Run: playwright install chromium")
        all_good = False

    # 3. Node.js Check (for JS Reverse Engineering Sandbox)
    node_path = shutil.which("node")
    if node_path:
        try:
            res = subprocess.run([node_path, "-v"], capture_output=True, text=True, timeout=2.0)
            ver = res.stdout.strip()
            table.add_row("Node.js Runtime", "[bold green]PASS[/bold green]", f"{ver} installed ({node_path})", "[green]JS Sandbox Ready[/green]")
        except Exception:
            table.add_row("Node.js Runtime", "[bold yellow]WARN[/bold yellow]", "Node binary exists but failed to respond", "Verify Node.js installation")
    else:
        table.add_row("Node.js Runtime", "[bold yellow]OPTIONAL[/bold yellow]", "Node.js not in system PATH", "Optional: Install Node.js for JS signing")

    # 4. LLM API Key Configuration Check
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if api_key and api_key != "your_api_key_here":
        masked = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
        provider = "DashScope" if os.environ.get("DASHSCOPE_API_KEY") else ("DeepSeek" if os.environ.get("DEEPSEEK_API_KEY") else "OpenAI-compatible")
        table.add_row("LLM API Key", "[bold green]PASS[/bold green]", f"{provider} ({masked})", "[green]Ready[/green]")
    else:
        table.add_row("LLM API Key", "[bold red]FAIL[/bold red]", "No active LLM API key detected in .env", "Copy .env.example to .env and set your key")
        all_good = False

    console.print(table)
    if all_good:
        console.print("\n[bold green]✓ System is fully ready for autonomous scraping![/bold green]\n")
    else:
        console.print("\n[bold yellow]! Please address items marked FAIL/WARN to ensure optimal experience.[/bold yellow]\n")


if __name__ == "__main__":
    app()
