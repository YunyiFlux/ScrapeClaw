import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scrapeclaw.api import synthesize
from scrapeclaw.exceptions import (
    BrowserLaunchError,
    ConfigurationError,
    ExecutionGateError,
    ReverseEngineeringError,
    ScrapeClawError,
    TargetNavigationError,
)

console = Console()


class WizardBack(Exception):
    pass


class WizardExit(Exception):
    pass


class WizardSession:
    def __init__(self):
        self.url: str = ""
        self.goal: str = ""
        self.engine: str = "httpx"
        self.format: str = "json"
        self.headless: bool = True
        self.session_file: Optional[str] = None
        self.data_output: Optional[str] = None
        self.output_script: Optional[str] = None

    def ask(
        self,
        prompt: str,
        *,
        default: str = "",
        choices: Optional[List[str]] = None,
        allow_empty: bool = False,
    ) -> str:
        choices_hint = f" ({'/'.join(choices)})" if choices else ""
        default_hint = f" [default: {default}]" if default else ""
        full_prompt = f"  [bold cyan]?[/bold cyan] {prompt}{choices_hint}{default_hint}: "

        while True:
            try:
                val = console.input(full_prompt).strip()
            except (KeyboardInterrupt, EOFError):
                raise WizardExit()

            if not val and default:
                val = default

            if val.lower() in ("q", "quit", "exit"):
                raise WizardExit()

            if val.lower() in ("b", "back"):
                raise WizardBack()

            if not val and not allow_empty:
                console.print("  [red]输入不能为空，请重新输入或输入 'b' 返回，'q' 退出。[/red]")
                continue

            if choices and val.lower() not in [c.lower() for c in choices]:
                console.print(f"  [red]无效选项，请输入以下值之一: {', '.join(choices)}[/red]")
                continue

            return val


def run_interactive_wizard() -> None:
    header = (
        "[bold cyan]🦞 ScrapeClaw 交互式爬虫生成向导[/bold cyan]\n"
        "[dim]输入 'b' 可返回上一步，输入 'q' 可随时退出[/dim]"
    )
    console.print(Panel(header, border_style="cyan"))

    session = WizardSession()
    step = 1
    is_custom_mode = False

    while True:
        try:
            if step == 1:
                console.print("\n[bold green][步骤 1/2] 目标网址 (Target URL)[/bold green]")
                console.print("[dim]请输入您要逆向抓取的目标单页应用 (SPA) 网址，例如: https://quotes.toscrape.com/js/[/dim]")
                session.url = session.ask("目标网址", default=session.url)
                if not session.url.startswith(("http://", "https://")):
                    console.print("  [red]网址格式不正确，必须以 http:// 或 https:// 开头[/red]")
                    continue
                step = 2

            elif step == 2:
                console.print("\n[bold green][步骤 2/2] 采集需求 (Extraction Goal)[/bold green]")
                console.print("[dim]请用自然语言描述您想要提取的数据字段，例如: 提取名言文本、作者姓名和分类标签[/dim]")
                session.goal = session.ask("采集需求", default=session.goal)
                step = 3

            elif step == 3:
                # 决策卡片 (极速模式 vs 定制模式)
                table = Table(title="📋 任务配置摘要", border_style="cyan", show_header=False)
                table.add_column("Key", style="bold yellow", width=15)
                table.add_column("Value", style="white")
                table.add_row("🎯 目标网址", session.url)
                table.add_row("📋 采集需求", session.goal)
                table.add_row("⚡ 默认引擎", f"{session.engine} (轻量异步)")
                table.add_row("📊 默认导出", f"{session.format} (./output/data.{session.format})")
                table.add_row("🛡️ 探针模式", "Headless (无头静默)")
                console.print("\n")
                console.print(table)

                console.print(
                    "\n[bold green]按 [Enter] 以极速模式直接启动[/bold green] | "
                    "[bold yellow]输入 [c] 进入定制模式[/bold yellow] | "
                    "[dim][b] 返回修改 | [q] 退出[/dim]"
                )
                choice = session.ask("请确认操作", default="start", allow_empty=True)

                if choice in ("c", "custom", "定制", "2"):
                    is_custom_mode = True
                    step = 4
                else:
                    # 极速模式启动
                    break

            elif step == 4:
                # 定制模式: 引擎选择
                console.print("\n[bold yellow][定制步骤 1/3] 选择爬虫引擎[/bold yellow]")
                console.print("  [1] httpx (轻量单文件异步爬虫，适合数据脚本) [默认]")
                console.print("  [2] scrapy (工业级多文件脚手架工程)")
                console.print("  [3] drission (DrissionPage 浏览器抗检测模式)")
                engine_map = {"1": "httpx", "2": "scrapy", "3": "drission", "httpx": "httpx", "scrapy": "scrapy", "drission": "drission"}
                cur_key = "1" if session.engine == "httpx" else ("2" if session.engine == "scrapy" else "3")
                ans = session.ask("选择引擎 [1-3]", default=cur_key, choices=["1", "2", "3", "httpx", "scrapy", "drission"])
                session.engine = engine_map.get(ans, "httpx")
                step = 5

            elif step == 5:
                # 定制模式: 导出格式
                console.print("\n[bold yellow][定制步骤 2/3] 数据导出格式[/bold yellow]")
                console.print("  [1] JSON (标准 JSON 文件) [默认]")
                console.print("  [2] CSV (带 Excel BOM 防乱码)")
                console.print("  [3] JSONL (换行分割 JSON)")
                console.print("  [4] NONE (仅生成爬虫代码，不单独保存数据)")
                fmt_map = {"1": "json", "2": "csv", "3": "jsonl", "4": "none"}
                cur_key = "1" if session.format == "json" else ("2" if session.format == "csv" else ("3" if session.format == "jsonl" else "4"))
                ans = session.ask("选择格式 [1-4]", default=cur_key, choices=["1", "2", "3", "4", "json", "csv", "jsonl", "none"])
                session.format = fmt_map.get(ans, "json")
                step = 6

            elif step == 6:
                # 定制模式: 高级环境与确认
                console.print("\n[bold yellow][定制步骤 3/3] 运行环境与会话凭据[/bold yellow]")
                headless_ans = session.ask("启用无头浏览器模式 (Headless)?", default="y" if session.headless else "n", choices=["y", "n", "yes", "no"])
                session.headless = headless_ans.lower() in ("y", "yes")

                session_file_ans = session.ask("已登录 Cookies/Session 文件路径 (无则直接回车跳过)", default=session.session_file or "", allow_empty=True)
                session.session_file = session_file_ans if session_file_ans else None
                step = 7

            elif step == 7:
                # 定制模式最终确认卡片
                table = Table(title="🛠️ 定制任务完整配置", border_style="yellow", show_header=False)
                table.add_column("Key", style="bold yellow", width=15)
                table.add_column("Value", style="white")
                table.add_row("🎯 目标网址", session.url)
                table.add_row("📋 采集需求", session.goal)
                table.add_row("⚡ 爬虫引擎", session.engine)
                table.add_row("📊 导出格式", session.format)
                table.add_row("🛡️ 探针模式", "Headless" if session.headless else "实机有头窗口")
                if session.session_file:
                    table.add_row("🔑 会话凭据", session.session_file)
                console.print("\n")
                console.print(table)

                console.print("\n[bold green]按 [Enter] 立即以定制配置启动[/bold green] | [dim][b] 返回修改 | [q] 退出[/dim]")
                session.ask("确认启动", default="start", allow_empty=True)
                break

        except WizardBack:
            if step > 1:
                step -= 1
                if step == 3 and is_custom_mode:
                    step = 2
            continue
        except WizardExit:
            console.print("\n[yellow]已退出 ScrapeClaw 交互式向导。[/yellow]")
            return

    # 执行爬取
    _execute_wizard_task(session)


def _execute_wizard_task(session: WizardSession) -> None:
    data_out = None
    if session.format != "none":
        ext = session.format if session.format in ("json", "csv", "jsonl") else "json"
        data_out = f"./output/extracted_data.{ext}"

    script_out = session.output_script or (
        "./crawlers/scrapeclaw_project" if session.engine == "scrapy" else "./spiders/generated_spider.py"
    )

    console.print("\n[bold cyan]🚀 Agent 启动逆向与爬虫合成流程...[/bold cyan]")

    def cli_event_handler(kind: str, payload: dict):
        if kind == "step_start":
            console.print(f"\n[bold blue]-- Round {payload.get('step')} --[/bold blue]")
        elif kind == "step_thought":
            console.print(f"[dim]{payload.get('thought', '')}[/dim]")
        elif kind == "tool_call":
            console.print(f"[yellow][Tool Call][/yellow] [bold]{payload.get('tool', '')}[/bold]")
        elif kind == "tool_result":
            console.print(f"[green][Tool Result][/green] {payload.get('summary', '')}")
        elif kind == "completed":
            console.print(f"\n[bold green][SUCCESS][/bold green] {payload.get('reason', '')}")
        elif kind == "captcha_detected":
            console.print("[bold red]⚠️ 检测到人机验证/验证码拦截，正在尝试自动绕过...[/bold red]")
        elif kind == "captcha_resolved":
            console.print("[bold green]✓ 人机验证已成功解除！继续执行逆向探查...[/bold green]")

    try:
        crawler = synthesize(
            url=session.url,
            goal=session.goal,
            engine=session.engine,
            output=script_out,
            data_output=data_out,
            format=session.format if session.format != "none" else None,
            session_file=session.session_file,
            headless=session.headless,
            on_event=cli_event_handler,
        )

        items = crawler.sample_data or []
        if items:
            preview_count = min(len(items), 5)
            keys = list(items[0].keys())[:5]
            table = Table(
                title=f"🎉 目标数据提取成功 (预览前 {preview_count} 条 / 共 {len(items)} 条)",
                border_style="cyan",
                header_style="bold magenta",
            )
            for k in keys:
                table.add_column(str(k), overflow="fold")
            for item in items[:preview_count]:
                table.add_row(*[str(item.get(k, ""))[:67] for k in keys])
            console.print("\n")
            console.print(table)

        pass_summary = (
            f"[bold green]✔ 逆向与爬虫合成完成！[/bold green]\n\n"
            f"[cyan]目标网址:[/cyan] {session.url}\n"
            f"[cyan]采集目标:[/cyan] {session.goal}\n"
            f"[cyan]爬虫脚本:[/cyan] {Path(script_out).resolve()}\n"
        )
        if data_out and items:
            pass_summary += f"[cyan]导出数据:[/cyan] {Path(data_out).resolve()} ({len(items)} records)\n"
        pass_summary += f"[dim]独立运行该脚本: [bold green]python {Path(script_out).resolve()}[/bold green][/dim]"
        console.print(Panel(pass_summary, title="完成", border_style="green"))

    except ConfigurationError as e:
        console.print(f"\n[bold red]配置错误:[/bold red] {e}")
    except ScrapeClawError as e:
        console.print(f"\n[bold red]执行失败:[/bold red] {e}")
