from pathlib import Path
"""AST Static Safety Checker & Import Pre-flight Checker."""
import ast
from typing import Tuple

BLOCKED_NAMES = {"os", "subprocess", "shutil", "sys"}
BLOCKED_CALLS = {"system", "popen", "rmtree", "eval", "exec"}

ALLOWED_SANDBOX_MODULES = {
    "httpx", "httpcore", "asyncio", "json", "pydantic", "csv", "xml",
    "re", "html", "string", "base64", "hashlib", "sys", "time", "datetime",
    "math", "argparse", "pathlib", "logging", "typing", "urllib",
    "tenacity", "scrapy", "itemadapter", "DrissionPage", "playwright",
    "subprocess", "os", "shutil", "scrapeclaw"
}

def check_script_safety(code: str) -> Tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error in synthesized code: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in BLOCKED_CALLS:
                    return False, f"Blocked dangerous function call: {node.func.attr}"
            elif isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec", "__import__"):
                    return False, f"Blocked builtin call: {node.func.id}"
    return True, "Code passed AST safety check"

def check_script_imports(code: str) -> Tuple[bool, str]:
    """Static pre-flight check to ensure all imported packages are pre-installed in the offline sandbox."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error in crawler code: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                pkg = alias.name.split(".")[0]
                if pkg not in ALLOWED_SANDBOX_MODULES:
                    return False, (
                        f"Module '{pkg}' is NOT pre-installed in the offline execution sandbox. "
                        f"Allowed modules: {sorted(ALLOWED_SANDBOX_MODULES)}. "
                        f"Please use standard library modules (e.g., 'html.parser' instead of '{pkg}')."
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                pkg = node.module.split(".")[0]
                if pkg not in ALLOWED_SANDBOX_MODULES:
                    return False, (
                        f"Module '{pkg}' is NOT pre-installed in the offline execution sandbox. "
                        f"Allowed modules: {sorted(ALLOWED_SANDBOX_MODULES)}. "
                        f"Please use standard library modules (e.g., 'html.parser' instead of '{pkg}')."
                    )
    return True, "Imports verified against sandbox whitelist"


def check_project_safety(project_dir: Path) -> Tuple[bool, str]:
    """Recursively check all python files in a multi-file project for AST safety."""
    if not project_dir.exists():
        return False, f"Project directory does not exist: {project_dir}"
    
    for py_file in project_dir.rglob("*.py"):
        try:
            code = py_file.read_text(encoding="utf-8")
        except Exception as e:
            return False, f"Failed to read file {py_file}: {e}"
        safe, reason = check_script_safety(code)
        if not safe:
            return False, f"Safety violation in {py_file.name}: {reason}"
    return True, "All project files passed AST safety check"
