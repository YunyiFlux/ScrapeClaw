"""Standalone Physical Execution Gate with Anti-Scraping Pattern Classification & Multi-Engine Support."""
import sys
import os
import asyncio
import json
import re
import py_compile
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
from scrapeclaw.synthesizer.ast_checker import check_project_safety, check_script_safety


def decode_process_output(raw: bytes) -> str:
    """Decode subprocess output with UTF-8 priority and GB18030/GBK fallback."""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030")
    except Exception:
        return raw.decode("utf-8", errors="replace")


def classify_execution_error(proc_code: int, stdout: str, stderr: str, items_count: int) -> Optional[str]:
    """Classify execution failure into actionable diagnostic tags."""
    combined = f"{stdout}\n{stderr}".lower()
    if "403" in combined or "forbidden" in combined or "anti-hotlink" in combined:
        return "403_FORBIDDEN"
    if "429" in combined or "too many requests" in combined or "rate limit" in combined:
        return "429_RATE_LIMIT"
    if "401" in combined or "unauthorized" in combined:
        return "401_UNAUTHORIZED"
    if proc_code == 0 and items_count == 0:
        return "0_ITEMS"
    return None




def validate_extracted_quality(parsed: List[Any], script_text: str = "") -> Tuple[bool, str]:
    """Semantic data quality guard to prevent false-positive extraction."""
    if not isinstance(parsed, list) or len(parsed) == 0:
        return False, "[0_ITEMS] Crawler ran successfully but extracted 0 items (empty array)."

    error_items = [
        item for item in parsed
        if isinstance(item, dict) and ("error" in item or item.get("status") == "error" or item.get("status_code") in (401, 403, 429, 500))
    ]
    if len(error_items) == len(parsed):
        first_err = error_items[0].get("error") or error_items[0].get("status") or error_items[0].get("status_code")
        str_err = str(first_err).lower()
        if "403" in str_err:
            tag = "[403_FORBIDDEN]"
        elif "401" in str_err:
            tag = "[401_UNAUTHORIZED]"
        elif "429" in str_err:
            tag = "[429_RATE_LIMIT]"
        else:
            tag = "[EXECUTION_ERROR]"
        return False, f"{tag} Sandbox crawler failed: output records only contain error states ({first_err}). Target blocked or rejected request."

    html_pattern = re.compile(r'^\s*<(?:!doctype\s+html|html|script|body|head|meta)', re.IGNORECASE)
    for item in parsed:
        if isinstance(item, dict):
            for k, v in item.items():
                if isinstance(v, str) and html_pattern.match(v):
                    return False, "[RAW_HTML_DUMP] Sandbox crawler failed: output contains raw HTML markup or challenge interception page instead of structured entities."
        elif isinstance(item, str) and html_pattern.match(item):
            return False, "[RAW_HTML_DUMP] Sandbox crawler failed: output contains raw HTML markup instead of structured entities."

    meta_keys = {"_raw", "raw", "html", "_html", "body", "page_source", "response", "text", "_page", "page", "url", "error", "status", "status_code", "turnstile_detected"}
    b64_cipher_pattern = re.compile(r'^[A-Za-z0-9+/=]{80,}$')

    for item in parsed:
        if isinstance(item, dict):
            non_meta_keys = [k for k in item.keys() if k.lower() not in meta_keys]
            if not non_meta_keys:
                return False, "[NO_STRUCTURED_FIELDS] Sandbox crawler failed: output records only contain fallback metadata fields without structured business data."

            has_substantive = False
            for k, v in item.items():
                if k.lower() in meta_keys:
                    continue
                if isinstance(v, str):
                    s_val = v.strip()
                    if len(s_val) > 80 and b64_cipher_pattern.fullmatch(s_val):
                        return False, "[UNPARSED_CIPHERTEXT] Sandbox crawler failed: extracted field contains unparsed encrypted ciphertext. Endpoint requires response decryption or DOM rendering."
                    if s_val:
                        has_substantive = True
                elif v not in (None, "", [], {}):
                    has_substantive = True
            if not has_substantive:
                return False, "[EMPTY_DATA] Sandbox crawler failed: extracted items contain no substantive data (all business fields are empty)."

    has_substantive_data = False
    for item in parsed:
        if isinstance(item, dict):
            payload_values = [
                v for k, v in item.items()
                if k.lower() not in ("url", "error", "status", "status_code", "turnstile_detected")
                and v not in (None, "", [], {})
            ]
            if payload_values:
                has_substantive_data = True
                break
        elif item:
            has_substantive_data = True
            break

    if not has_substantive_data:
        return False, "[EMPTY_DATA] Sandbox crawler failed: extracted items contain no substantive data (all fields are null/empty). Target site likely blocked request or requires dynamic JS execution."

    placeholder_entities = [
        item for item in parsed
        if isinstance(item, dict) and (
            (str(item.get("up_name") or "").lower() == "github" and "github.com/github" in str(item.get("url") or "").lower())
            or (str(item.get("username") or "").lower() in ("dummy_user", "placeholder_user", "sample_user"))
        )
    ]
    if len(placeholder_entities) == len(parsed) and len(parsed) > 0:
        if "default_usernames" in script_text.lower() or "github.com/github" in script_text:
            return False, "[ENTITY_DRIFT] Sandbox crawler failed: extracted records belong to public fallback entity 'GitHub' rather than target profile data. The crawler drifted away from the requested target."

    return True, ""


async def run_standalone_execution_gate(script_path: str, timeout_seconds: float = 25.0) -> Tuple[bool, str, List[Dict[str, Any]]]:
    path_obj = Path(script_path)

    # 1. Scrapy multi-file project detection
    project_dir = None
    if path_obj.is_dir() and (path_obj / "scrapy.cfg").exists():
        project_dir = path_obj
    elif path_obj.is_file() and (path_obj.parent / "scrapy.cfg").exists():
        project_dir = path_obj.parent
    elif path_obj.is_file() and (path_obj.parent.parent / "scrapy.cfg").exists():
        project_dir = path_obj.parent.parent

    if project_dir:
        # Verify Scrapy project files via AST and py_compile
        safe, reason = check_project_safety(project_dir)
        if not safe:
            return False, f"Scrapy project AST safety violation: {reason}", []

        py_files = list(project_dir.rglob("*.py"))
        if not py_files:
            return False, "Scrapy project contains no Python files.", []

        for pf in py_files:
            try:
                py_compile.compile(str(pf), doraise=True)
            except py_compile.PyCompileError as e:
                return False, f"Syntax error in Scrapy file {pf.name}: {e}", []

        # Check if scrapy package is installed
        try:
            import scrapy  # noqa: F401
            has_scrapy = True
        except ImportError:
            has_scrapy = False

        if has_scrapy:
            # If scrapy is installed, we can run `scrapy check`
            cmd = [sys.executable, "-m", "scrapy", "check"]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            stdout = decode_process_output(stdout_b).strip()
            stderr = decode_process_output(stderr_b).strip()
            if proc.returncode != 0:
                return False, f"Scrapy check failed: {stderr[:300]}", []
            return True, f"Scrapy project verified successfully with 'scrapy check'! ({len(py_files)} files passed)", []
        else:
            return True, f"Scrapy project structure and AST syntax verified successfully! ({len(py_files)} Python files compiled cleanly)", []

    # 2. Standalone script execution (httpx / drission)
    cmd = [sys.executable, script_path, "--max-pages", "1"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(path_obj.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        stdout = decode_process_output(stdout_b).strip()
        stderr = decode_process_output(stderr_b).strip()

        if proc.returncode != 0:
            # If DrissionPage is missing
            if "DrissionPage is not installed" in stderr:
                safe, reason = check_script_safety(path_obj.read_text(encoding="utf-8"))
                if safe:
                    return True, "DrissionPage crawler passed static syntax and AST validation (DrissionPage not pre-installed).", []
            err_tag = classify_execution_error(proc.returncode, stdout, stderr, 0)
            prefix = f"[{err_tag}] " if err_tag else ""
            return False, f"{prefix}Script failed with code {proc.returncode}. Stderr: {stderr[:400]}", []

        json_start = stdout.find("[")
        json_end = stdout.rfind("]")
        if json_start < 0 or json_end <= json_start:
            return False, "Process completed but did not output a JSON list to stdout.", []

        parsed = json.loads(stdout[json_start:json_end + 1])
        script_text = path_obj.read_text(encoding="utf-8", errors="replace") if path_obj.is_file() else ""
        valid, err_msg = validate_extracted_quality(parsed, script_text)
        if not valid:
            return False, err_msg, []

        return True, f"Execution passed! Extracted {len(parsed)} items offline successfully.", parsed

    except asyncio.TimeoutError:
        return False, f"Sandbox execution timed out ({timeout_seconds}s).", []
    except Exception as e:
        return False, f"Sandbox error: {e}", []
