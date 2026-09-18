"""Browser Context RPC Signing Bridge (Story 12).

Provides:
1. BrowserRPCBridge: Executes JavaScript signature generation directly inside an active browser context.
2. Lightweight evaluation without full page reloading.
3. Ideal for WebAssembly (Wasm) or heavily Webpack-bundled encryption routines.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Tuple
from playwright.async_api import Page

logger = logging.getLogger(__name__)


class BrowserRPCBridge:
    """RPC bridge for calculating client signatures within an active browser runtime."""

    def __init__(self, page: Optional[Page] = None):
        self.page = page

    def set_page(self, page: Page) -> None:
        self.page = page

    async def evaluate_signature(
        self,
        expression_or_func: str,
        arguments: Any = None,
        timeout_ms: int = 5000,
    ) -> Tuple[bool, str, Any]:
        """Execute a signing expression or function within the page context.
        
        Args:
            expression_or_func: JS function name (e.g. 'window.sign') or inline expression.
            arguments: Arguments to pass to the function.
            timeout_ms: Evaluation timeout in milliseconds.
            
        Returns:
            Tuple[bool, str, Any]: (success, message, result)
        """
        if not self.page:
            return False, "Browser page is not available for RPC evaluation.", None

        js_wrapper = """
        async ([expr, args]) => {
            try {
                // If it's a global function name
                if (typeof window[expr] === 'function') {
                    const res = await window[expr](args);
                    return { ok: true, data: res };
                }
                // If it's an evaluation function expression
                const fn = new Function('args', 'return (' + expr + ')(args);');
                const res = await fn(args);
                return { ok: true, data: res };
            } catch (e) {
                return { ok: false, error: e.stack || String(e) };
            }
        }
        """
        try:
            res = await self.page.evaluate(js_wrapper, [expression_or_func, arguments])
            if isinstance(res, dict) and res.get("ok"):
                return True, "RPC evaluation succeeded.", res.get("data")
            err_msg = res.get("error", "Unknown RPC error") if isinstance(res, dict) else str(res)
            return False, f"RPC evaluation failed: {err_msg[:300]}", None
        except Exception as e:
            return False, f"Browser RPC error: {str(e)[:300]}", None
