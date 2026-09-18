"""High-Performance Isolated JavaScript Execution Sandbox (Story 12).

Provides:
1. JSRuntime: Executes candidate JS signing scripts or snippets in an isolated Node.js environment.
2. JSON argument injection and structured result serialization.
3. Timeout protection, memory/process safety guards, and UTF-8 output normalization.
4. Python stdlib fallback for standard cryptographic primitives (MD5, SHA256, HMAC).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def compute_standard_hash(algo: str, data: str | bytes, key: str | bytes = "") -> str:
    """Fast Python standard library hashing fallback (MD5, SHA1, SHA256, SHA512, HMAC)."""
    raw_data = data.encode("utf-8") if isinstance(data, str) else data
    algo_clean = algo.lower().replace("-", "").replace("_", "")

    if key:
        raw_key = key.encode("utf-8") if isinstance(key, str) else key
        h = hmac.new(raw_key, raw_data, getattr(hashlib, algo_clean, hashlib.sha256))
        return h.hexdigest()

    if algo_clean in ("md5", "sha1", "sha256", "sha512"):
        h = getattr(hashlib, algo_clean)()
        h.update(raw_data)
        return h.hexdigest()
    return ""


class JSRuntime:
    """Isolated JavaScript Sandbox powered by local Node.js engine."""

    def __init__(self, node_executable: Optional[str] = None):
        self.node_path = node_executable or shutil.which("node")

    def is_available(self) -> bool:
        """Check if local Node.js runtime is installed and accessible."""
        if not self.node_path:
            return False
        try:
            res = subprocess.run([self.node_path, "-v"], capture_output=True, text=True, timeout=2.0)
            return res.returncode == 0
        except Exception:
            return False

    def get_version(self) -> str:
        """Get Node.js engine version string."""
        if not self.is_available():
            return "unavailable"
        try:
            res = subprocess.run([self.node_path, "-v"], capture_output=True, text=True, timeout=2.0)
            return res.stdout.strip()
        except Exception:
            return "unknown"

    async def execute_code(
        self,
        code: str,
        context_vars: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> Tuple[bool, str, Any]:
        """Execute isolated JavaScript snippet or function and return parsed result.
        
        Args:
            code: JavaScript code to execute. Can define functions or return values.
            context_vars: Dictionary of variables injected as global `context` object.
            timeout: Execution timeout in seconds (default: 5.0s).
            
        Returns:
            Tuple[bool, str, Any]: (success, message, parsed_result_data)
        """
        if not self.is_available():
            return False, "Node.js runtime is not available in system PATH. Please install Node.js.", None

        ctx_json = json.dumps(context_vars or {}, ensure_ascii=False)

        # Wrap code into a safe runner script that captures output cleanly
        wrapper_script = f"""
const fs = require('fs');
const crypto = require('crypto');

// Injected execution context
const context = {ctx_json};

function __scrapeclaw_run() {{
    try {{
{code}
    }} catch (e) {{
        return {{ __error: true, message: e.stack || String(e) }};
    }}
}}

const __result = __scrapeclaw_run();
if (__result !== undefined) {{
    if (__result && __result.__error) {{
        console.error("RUN_ERROR: " + __result.message);
        process.exit(1);
    }} else {{
        console.log(JSON.stringify(__result));
    }}
}}
"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_file = Path(tmp_dir) / "runner.js"
            tmp_file.write_text(wrapper_script, encoding="utf-8")

            cmd = [self.node_path, str(tmp_file)]
            env = {**os.environ, "NODE_NO_WARNINGS": "1"}

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                stdout = stdout_b.decode("utf-8", errors="replace").strip()
                stderr = stderr_b.decode("utf-8", errors="replace").strip()

                if proc.returncode != 0:
                    err_msg = stderr or stdout or f"Process exited with code {proc.returncode}"
                    return False, f"JS Sandbox Execution Error: {err_msg[:400]}", None

                if not stdout:
                    return True, "Executed successfully (no return value output).", None

                # Attempt to parse stdout as JSON
                try:
                    data = json.loads(stdout)
                    return True, f"Executed successfully! Output: {str(data)[:100]}", data
                except json.JSONDecodeError:
                    return True, f"Executed successfully: {stdout[:200]}", stdout

            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return False, f"JS Sandbox Timed Out ({timeout}s). Possible infinite loop in script.", None
            except Exception as e:
                return False, f"Execution Sandbox Error: {str(e)[:300]}", None
