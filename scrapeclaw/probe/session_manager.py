"""Session Manager & Credential Persistence Lineage (Story 8).

Provides:
1. Unified session storage data model (Cookies, LocalStorage, Custom Auth Tokens).
2. Universal Credential Normalizer supporting:
   - Playwright storage_state standard JSON format
   - Raw Cookie strings (directly copied from browser DevTools, single or multi-line)
   - Netscape tab-delimited cookie format (curl / cookie-txt export format)
   - Header strings ("Cookie: foo=bar; baz=qux")
3. Automated Domain & Path Inheritance Tree (explicit > target_url > parent wildcard domain).
4. Bidirectional conversions between Playwright, httpx, and Header formats.
5. Lineage propagation for agent solver, code synthesis, and offline execution sandbox.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def extract_clean_domain(url_or_host: str) -> str:
    """Extract and sanitize hostname from a URL, host string, or host:port."""
    if not url_or_host:
        return ""
    val = url_or_host.strip()
    if "://" in val:
        val = urlparse(val).hostname or val
    if ":" in val:
        val = val.split(":")[0]
    return val.strip()


def derive_domain_hierarchy(target_url_or_host: str) -> Tuple[str, str, str]:
    """Derive (hostname, root_domain, wildcard_domain) from target URL or host string.
    
    Example:
        'https://sub.github.com/settings' -> ('sub.github.com', 'github.com', '.github.com')
    """
    host = extract_clean_domain(target_url_or_host)
    if not host:
        return "", "", ""
    
    # Check IP or localhost
    if host.replace(".", "").isdigit() or host == "localhost":
        return host, host, host

    parts = host.split(".")
    if len(parts) >= 2:
        if len(parts) >= 3 and parts[-2] in ("com", "edu", "gov", "org", "net", "co", "ac"):
            root = ".".join(parts[-3:])
        else:
            root = ".".join(parts[-2:])
    else:
        root = host

    wildcard = f".{root}" if not root.startswith(".") else root
    return host, root, wildcard


class CookieItem(BaseModel):
    """Normalized cookie model compatible with Playwright, httpx, and curl."""
    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: Optional[float] = None
    httpOnly: bool = False
    secure: bool = False
    sameSite: str = "Lax"  # "Strict", "Lax", "None"

    def to_playwright_dict(self, fallback_domain: str = "", fallback_url: str = "") -> Dict[str, Any]:
        """Convert to Playwright-compatible cookie dictionary.
        
        Playwright strictly mandates either (domain + path) or (url).
        """
        d: Dict[str, Any] = {
            "name": self.name,
            "value": self.value,
            "path": self.path or "/",
            "secure": self.secure,
            "httpOnly": self.httpOnly,
        }
        dom = extract_clean_domain(self.domain or fallback_domain)
        if dom:
            d["domain"] = dom
        elif fallback_url:
            d["url"] = fallback_url

        if self.expires and self.expires > 0:
            d["expires"] = self.expires
        if self.sameSite in ("Strict", "Lax", "None"):
            d["sameSite"] = self.sameSite
        return d


class SessionBundle(BaseModel):
    """Comprehensive snapshot of authentication credentials."""
    domain: str = ""
    cookies: List[CookieItem] = Field(default_factory=list)
    local_storage: Dict[str, str] = Field(default_factory=dict)
    custom_headers: Dict[str, str] = Field(default_factory=dict)
    saved_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""

    def resolve_for_target(self, target_url: str) -> SessionBundle:
        """Bind unassigned cookie domains using the target URL's domain hierarchy."""
        if not target_url:
            return self
        host, root, wildcard = derive_domain_hierarchy(target_url)
        target_domain = wildcard or root or host
        if not self.domain:
            self.domain = target_domain
        
        for c in self.cookies:
            if not c.domain:
                c.domain = target_domain
        return self

    def to_playwright_cookies(self, fallback_domain: str = "", fallback_url: str = "") -> List[Dict[str, Any]]:
        """Convert all cookies to Playwright format with intelligent fallback domain/url."""
        target_dom = extract_clean_domain(self.domain or fallback_domain)
        return [c.to_playwright_dict(fallback_domain=target_dom, fallback_url=fallback_url) for c in self.cookies]

    def to_httpx_cookies(self) -> Dict[str, str]:
        """Convert to httpx key-value cookie mapping."""
        return {c.name: c.value for c in self.cookies}

    def to_cookie_header(self) -> str:
        """Convert to HTTP 'Cookie: ...' header string."""
        return "; ".join(f"{c.name}={c.value}" for c in self.cookies)

    def is_empty(self) -> bool:
        return not bool(self.cookies or self.local_storage or self.custom_headers)


def parse_raw_cookie_string(raw: str, default_domain: str = "") -> List[CookieItem]:
    """Parse raw cookie strings in various formats into normalized CookieItem list.
    
    Supports:
    1. Standard semicolon key-value pairs: 'a=1; b=2'
    2. Multi-line cookie headers: 'Cookie: a=1\nCookie: b=2'
    3. Netscape tab-delimited format (curl / cookie.txt):
       'example.com\tTRUE\t/\tFALSE\t1735689600\tname\tvalue'
    """
    cookies: List[CookieItem] = []
    if not raw:
        return cookies

    clean_domain = extract_clean_domain(default_domain)
    lines = raw.strip().splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Format A: Netscape tab-delimited format (7 fields)
        if "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 7:
                dom, flag, path, sec, exp, name, val = parts[:7]
                try:
                    exp_float = float(exp) if exp and float(exp) > 0 else None
                except ValueError:
                    exp_float = None
                cookies.append(
                    CookieItem(
                        name=name.strip(),
                        value=val.strip(),
                        domain=dom.strip() or clean_domain,
                        path=path.strip() or "/",
                        expires=exp_float,
                        secure=sec.strip().upper() == "TRUE",
                    )
                )
                continue

        # Format B: Semicolon key-value pairs (optionally prefixed with 'Cookie: ')
        if line.lower().startswith("cookie:"):
            line = line[7:].strip()

        parts = line.split(";")
        for part in parts:
            part = part.strip()
            if "=" in part:
                name, val = part.split("=", 1)
                name = name.strip()
                val = val.strip()
                if name:
                    cookies.append(
                        CookieItem(
                            name=name,
                            value=val,
                            domain=clean_domain,
                            path="/",
                        )
                    )
    return cookies


def load_session_bundle(file_path_or_content: str, default_domain: str = "") -> SessionBundle:
    """Load credentials from file path or direct string content.
    
    Supports:
    1. Standard JSON format containing {"cookies": [...], "local_storage": {...}}
    2. Playwright storage_state format containing {"cookies": [...], "origins": [...]}
    3. Plain text raw cookie string format ("key1=val1; key2=val2")
    4. Netscape tab-delimited cookie file format
    """
    content = file_path_or_content.strip()
    p = Path(content)

    # If it's an existing file path, read its text
    if p.is_file():
        try:
            content = p.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning(f"Failed to read session file {p}: {e}")
            return SessionBundle(domain=default_domain)

    if not content:
        return SessionBundle(domain=default_domain)

    clean_dom = extract_clean_domain(default_domain)

    # Attempt 1: Parse as JSON (Playwright storage_state or custom bundle)
    if content.startswith("{"):
        try:
            data = json.loads(content)
            cookies: List[CookieItem] = []

            # Standard Playwright storage_state format
            if "cookies" in data and isinstance(data["cookies"], list):
                for c in data["cookies"]:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        cookies.append(
                            CookieItem(
                                name=c["name"],
                                value=c["value"],
                                domain=c.get("domain") or clean_dom,
                                path=c.get("path", "/"),
                                expires=c.get("expires"),
                                httpOnly=c.get("httpOnly", False),
                                secure=c.get("secure", False),
                                sameSite=c.get("sameSite", "Lax"),
                            )
                        )

            # Local storage extraction from Playwright origins
            local_storage: Dict[str, str] = {}
            if "origins" in data and isinstance(data["origins"], list):
                for origin in data["origins"]:
                    for item in origin.get("localStorage", []):
                        if "name" in item and "value" in item:
                            local_storage[item["name"]] = item["value"]
            elif "local_storage" in data and isinstance(data["local_storage"], dict):
                local_storage = data["local_storage"]

            custom_headers = data.get("custom_headers", {}) if isinstance(data.get("custom_headers"), dict) else {}
            domain = data.get("domain", clean_dom)

            return SessionBundle(
                domain=domain,
                cookies=cookies,
                local_storage=local_storage,
                custom_headers=custom_headers,
                saved_at=data.get("saved_at", datetime.now().isoformat()),
                description=data.get("description", "Imported from JSON"),
            )
        except Exception as e:
            logger.debug(f"JSON parse attempt failed, trying raw format: {e}")

    # Attempt 2: Parse as raw cookie string / Netscape format
    raw_cookies = parse_raw_cookie_string(content, default_domain=clean_dom)
    if raw_cookies:
        return SessionBundle(
            domain=clean_dom,
            cookies=raw_cookies,
            description="Imported from raw cookie content",
        )

    return SessionBundle(domain=clean_dom)


def save_session_bundle(bundle: SessionBundle, file_path: str | Path) -> None:
    """Save SessionBundle to a formatted JSON file."""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "domain": bundle.domain,
        "saved_at": datetime.now().isoformat(),
        "description": bundle.description or "ScrapeClaw Session Bundle",
        "cookies": [c.model_dump() for c in bundle.cookies],
        "local_storage": bundle.local_storage,
        "custom_headers": bundle.custom_headers,
    }

    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Successfully saved {len(bundle.cookies)} session cookies to {p}")
