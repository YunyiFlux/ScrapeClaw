"""Dynamic Browser JS Crypto Interception & Hooking Pipeline (Story 12).

Provides:
1. Client-side JavaScript hooks for Web Crypto APIs, Hashing, Base64, and custom sign functions.
2. Interception of dynamic signature request headers in fetch and XMLHttpRequest.
3. Structured CryptoCallSnapshot data models linking inputs, algorithms, and output tokens.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CryptoCallSnapshot(BaseModel):
    """Normalized snapshot of a client-side cryptographic operation."""
    call_type: str = Field(..., description="'hash', 'encrypt', 'base64', 'sign_header', 'custom_func'")
    function_name: str = Field(default="", description="Name of intercepted function or header")
    algorithm: Optional[str] = Field(default=None, description="e.g. 'SHA-256', 'AES-GCM', 'MD5'")
    input_data: Any = Field(default=None, description="Input payload, text, or parameters before transform")
    output_data: str = Field(default="", description="Generated hash, ciphertext, or signature token")
    timestamp: float = Field(default_factory=time.time)
    stack_summary: str = Field(default="", description="Truncated call stack origin")

    def to_summary(self) -> str:
        inp_preview = str(self.input_data)
        if len(inp_preview) > 80:
            inp_preview = inp_preview[:77] + "..."
        out_preview = str(self.output_data)
        if len(out_preview) > 60:
            out_preview = out_preview[:57] + "..."
        return f"[{self.call_type}:{self.function_name}] input='{inp_preview}' -> output='{out_preview}'"


def get_crypto_hook_js() -> str:
    """Generate lightweight JavaScript hook script to inject into page via add_init_script."""
    return """
(() => {
    if (window.__scrapeclaw_crypto_injected) return;
    window.__scrapeclaw_crypto_injected = true;
    window.__scrapeclaw_crypto_calls = [];

    function recordCall(callType, funcName, algorithm, inputData, outputData) {
        try {
            const stack = (new Error()).stack || "";
            const lines = stack.split("\\n").slice(2, 5).map(l => l.trim()).join(" <- ");
            window.__scrapeclaw_crypto_calls.push({
                call_type: callType,
                function_name: funcName,
                algorithm: algorithm,
                input_data: typeof inputData === "object" ? JSON.stringify(inputData) : String(inputData),
                output_data: String(outputData),
                timestamp: Date.now() / 1000,
                stack_summary: lines.substring(0, 200)
            });
            if (window.__scrapeclaw_crypto_calls.length > 200) {
                window.__scrapeclaw_crypto_calls.shift();
            }
        } catch (e) {}
    }

    function bufToHex(buf) {
        return Array.from(new Uint8Array(buf))
            .map(b => b.toString(16).padStart(2, '0'))
            .join('');
    }

    // 1. Hook window.btoa (Base64 encoding)
    if (typeof window.btoa === "function") {
        const origBtoa = window.btoa;
        window.btoa = function(str) {
            const res = origBtoa.apply(this, arguments);
            if (str && str.length > 2) {
                recordCall("base64", "btoa", null, str, res);
            }
            return res;
        };
    }

    // 2. Hook Web Crypto API (SubtleCrypto.digest and SubtleCrypto.encrypt)
    if (window.crypto && window.crypto.subtle) {
        const origDigest = window.crypto.subtle.digest;
        if (typeof origDigest === "function") {
            window.crypto.subtle.digest = async function(algo, data) {
                const res = await origDigest.apply(this, arguments);
                try {
                    let algoName = typeof algo === "string" ? algo : (algo && algo.name ? algo.name : "unknown");
                    let inStr = "";
                    if (data instanceof Uint8Array || data instanceof ArrayBuffer) {
                        inStr = (new TextDecoder()).decode(data);
                    }
                    const hexOut = bufToHex(res);
                    recordCall("hash", "crypto.subtle.digest", algoName, inStr, hexOut);
                } catch (e) {}
                return res;
            };
        }
    }

    // 3. Hook fetch for suspicious signature headers
    if (typeof window.fetch === "function") {
        const origFetch = window.fetch;
        window.fetch = function(input, init) {
            try {
                if (init && init.headers) {
                    const signKeys = ["x-sign", "_signature", "a_bogus", "x-bogus", "token", "sign", "x-s", "x-t", "s-token"];
                    const h = init.headers;
                    for (const key of signKeys) {
                        let val = null;
                        if (h instanceof Headers) {
                            val = h.get(key);
                        } else if (typeof h === "object") {
                            val = h[key] || h[key.toLowerCase()] || h[key.toUpperCase()];
                        }
                        if (val) {
                            const urlStr = typeof input === "string" ? input : (input && input.url ? input.url : "fetch");
                            recordCall("sign_header", "fetch.headers." + key, null, urlStr, val);
                        }
                    }
                }
            } catch (e) {}
            return origFetch.apply(this, arguments);
        };
    }

    // 4. Hook XMLHttpRequest setRequestHeader
    if (window.XMLHttpRequest) {
        const origSetHeader = window.XMLHttpRequest.prototype.setRequestHeader;
        window.XMLHttpRequest.prototype.setRequestHeader = function(header, value) {
            try {
                const signKeys = ["x-sign", "_signature", "a_bogus", "x-bogus", "token", "sign", "x-s", "x-t", "s-token"];
                const hLower = (header || "").toLowerCase();
                if (signKeys.some(k => hLower.includes(k))) {
                    recordCall("sign_header", "XHR.headers." + header, null, header, value);
                }
            } catch (e) {}
            return origSetHeader.apply(this, arguments);
        };
    }

    // 5. Intercept common global signing functions if assigned (window.sign, window.getSignature)
    const monitoredProps = ["sign", "getSignature", "get_sign", "hex_md5", "CryptoJS"];
    for (const prop of monitoredProps) {
        let internalVal = undefined;
        try {
            Object.defineProperty(window, prop, {
                configurable: true,
                enumerable: true,
                get: () => internalVal,
                set: (fn) => {
                    if (typeof fn === "function") {
                        internalVal = function() {
                            const out = fn.apply(this, arguments);
                            try {
                                const inStr = Array.from(arguments).map(a => typeof a === "object" ? JSON.stringify(a) : String(a)).join(", ");
                                recordCall("custom_func", "window." + prop, null, inStr, String(out));
                            } catch (e) {}
                            return out;
                        };
                    } else {
                        internalVal = fn;
                    }
                }
            });
        } catch (e) {}
    }
})();
"""


async def extract_crypto_snapshots_from_page(page: Any) -> List[CryptoCallSnapshot]:
    """Retrieve and clear buffered client-side cryptographic call snapshots from page."""
    if not page:
        return []
    try:
        raw_list = await page.evaluate("""
            () => {
                if (!window.__scrapeclaw_crypto_calls) return [];
                return window.__scrapeclaw_crypto_calls.splice(0, window.__scrapeclaw_crypto_calls.length);
            }
        """)
        snapshots = []
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, dict) and "call_type" in item:
                    snapshots.append(CryptoCallSnapshot(**item))
        return snapshots
    except Exception as e:
        logger.debug(f"Failed to extract crypto snapshots from page: {e}")
        return []
