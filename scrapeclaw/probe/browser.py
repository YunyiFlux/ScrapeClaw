from scrapeclaw.probe.stealth import get_stealth_js
"""Playwright Browser Probe & CDP Connector."""
import asyncio
import json
import logging
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, Callable
from urllib.parse import urlparse, parse_qs
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from scrapeclaw.traffic.store import TrafficStore
from scrapeclaw.traffic.models import RequestSnapshot
from scrapeclaw.probe.captcha_detector import CaptchaChallenge
from scrapeclaw.probe.captcha_solvers import CaptchaBypassBridge

logger = logging.getLogger(__name__)


class NavigationStatus(str, Enum):
    OK = "OK"
    AUTH_REDIRECT = "AUTH_REDIRECT"
    BOT_CHALLENGE = "BOT_CHALLENGE"
    ERROR_PAGE = "ERROR_PAGE"
    URL_DIVERGED = "URL_DIVERGED"


class NavigationOutcome(BaseModel):
    target_url: str
    landing_url: str = ""
    status: NavigationStatus = NavigationStatus.OK
    redirected: bool = False
    page_title: str = ""
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    diagnostic_hint: Optional[str] = None


class BrowserProbe:
    def __init__(
        self,
        traffic_store: TrafficStore,
        headless: bool = True,
        cdp_url: Optional[str] = None,
        session_file: Optional[str] = None,
        save_session_path: Optional[str] = None,
        auto_solve_captcha: bool = True,
        hitl_timeout_seconds: int = 60,
        on_captcha_event: Optional[Callable[[str, Any], None]] = None,
        target_url: Optional[str] = None,
    ):
        self.traffic_store = traffic_store
        self.headless = headless
        self.cdp_url = cdp_url
        self.session_file = session_file
        self.save_session_path = save_session_path
        self.target_url = target_url
        from scrapeclaw.probe.session_manager import derive_domain_hierarchy
        self.target_host, self.target_root_domain, self.target_wildcard_domain = derive_domain_hierarchy(target_url or "")
        self.target_domain = self.target_wildcard_domain or self.target_host
        self.session_bundle = None
        self.auto_solve_captcha = auto_solve_captcha
        self.last_resolved_captcha = None
        self.last_navigation_error = None
        self.last_navigation_outcome: Optional[NavigationOutcome] = None
        self.hitl_timeout_seconds = hitl_timeout_seconds
        self.on_captcha_event = on_captcha_event
        self.captcha_bridge = CaptchaBypassBridge(
            auto_solve=self.auto_solve_captcha,
            hitl_timeout_seconds=self.hitl_timeout_seconds,
            is_headless=self.headless,
            on_challenge_detected=lambda chal, path: (
                self.on_captcha_event("captcha_detected", {"challenge": chal, "screenshot_path": path})
                if self.on_captcha_event else None
            ),
        )
        self._pw = None
        self._browser = None
        self._context = None
        self.page: Optional[Page] = None
        self.crypto_calls: List[Any] = []

    async def start(self):
        self._pw = await async_playwright().start()
        if self.cdp_url:
            self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
            self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            from scrapeclaw.crypto.js_hooker import get_crypto_hook_js
            await self._context.add_init_script(get_crypto_hook_js())
        else:
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            await self._context.add_init_script(get_stealth_js())
            # JS Crypto Reverse Lineage (Story 12): Inject dynamic crypto hooker
            from scrapeclaw.crypto.js_hooker import get_crypto_hook_js
            await self._context.add_init_script(get_crypto_hook_js())

        # Session Lineage 2.0: Mount external session credentials if provided
        if self.session_file and self._context:
            from scrapeclaw.probe.session_manager import load_session_bundle
            self.session_bundle = load_session_bundle(self.session_file, default_domain=self.target_domain)
            if self.target_url:
                self.session_bundle.resolve_for_target(self.target_url)
            pw_cookies = self.session_bundle.to_playwright_cookies(
                fallback_domain=self.target_domain,
                fallback_url=self.target_url or "",
            )
            if pw_cookies:
                try:
                    await self._context.add_cookies(pw_cookies)
                    verified = await self._context.cookies()
                    logger.info(
                        "Successfully injected %d session cookies into browser context (active: %d, domain: %s)",
                        len(pw_cookies),
                        len(verified),
                        self.target_domain,
                    )
                except Exception as e:
                    logger.error("Failed to add session cookies to browser context: %s", e)

        self.page = await self._context.new_page()
        self.page.on("response", self._handle_response)

    async def _handle_response(self, response):
        try:
            req = response.request
            res_type = req.resource_type
            if res_type in ("image", "font", "stylesheet", "media"):
                return
            
            url = req.url
            method = req.method
            headers = dict(req.headers)

            # Defensive post_data extraction:
            # Playwright's req.post_data uses strict UTF-8 decode. Binary payloads (e.g. Protobuf,
            # Gzip beacons, log trackers) will raise UnicodeDecodeError and crash AsyncIOEventEmitter.
            post_data = None
            try:
                post_data = req.post_data
            except UnicodeDecodeError:
                try:
                    raw_buf = req.post_data_buffer
                    if raw_buf:
                        post_data = raw_buf.decode("utf-8", errors="replace")
                except Exception:
                    post_data = None
            except Exception:
                post_data = None

            parsed = urlparse(url)
            raw_qs = parse_qs(parsed.query)
            query_params = {k: v[0] if len(v) == 1 else v for k, v in raw_qs.items()}

            cookies = {}
            if "cookie" in headers:
                for item in headers["cookie"].split(";"):
                    if "=" in item:
                        k, v = item.strip().split("=", 1)
                        cookies[k] = v
            
            # Session Lineage 2.0: If Playwright omitted 'cookie' in request.headers (standard Chromium behavior),
            # dynamically resolve matching active cookies from the current BrowserContext.
            if not cookies and self._context:
                try:
                    active = await self.extract_session_cookies(domain=parsed.hostname)
                    if active:
                        cookies = active
                except Exception:
                    pass

            json_body = None
            if post_data:
                try:
                    json_body = json.loads(post_data)
                except Exception:
                    pass

            try:
                body = await response.body()
            except Exception:
                body = b""

            status_code = response.status
            resp_headers = dict(response.headers)
            content_type = resp_headers.get("content-type", "")

            snapshot = RequestSnapshot(
                url=url,
                method=method,
                headers=headers,
                cookies=cookies,
                query_params=query_params,
                post_data=post_data,
                json_body=json_body
            )

            self.traffic_store.record_traffic(
                resource_type=res_type,
                request=snapshot,
                status_code=status_code,
                response_headers=resp_headers,
                response_body=body,
                content_type=content_type
            )
        except Exception:
            # Global exception shield: prevents unhandled exceptions from breaking Playwright event loop
            pass

    async def check_and_handle_captcha(self) -> Optional[CaptchaChallenge]:
        """Detect bot challenges / Turnstile and execute bypass bridge."""
        if not self.page:
            return None
        try:
            challenge = await self.captcha_bridge.detect_and_bypass(self.page)
            if challenge:
                self.last_resolved_captcha = challenge
                if self.on_captcha_event:
                    self.on_captcha_event("captcha_resolved", {"challenge": challenge})
                try:
                    await self.extract_session_cookies()
                except Exception:
                    pass
                return challenge
            else:
                self.last_resolved_captcha = None
        except Exception as e:
            logger.debug(f"Captcha detection/bypass encountered error: {e}")
        return None

    async def navigate(self, url: str, wait_seconds: int = 3) -> int:
        if not self.page:
            return 0
        before_count = len(self.traffic_store.records)
        self.last_navigation_error = None
        self.last_navigation_outcome = None

        # On-demand session injection for current navigation URL
        if self.session_bundle and not self.session_bundle.is_empty() and self._context:
            try:
                existing = await self._context.cookies([url])
                if not existing:
                    from scrapeclaw.probe.session_manager import derive_domain_hierarchy
                    h, r, w = derive_domain_hierarchy(url)
                    extra_cookies = self.session_bundle.to_playwright_cookies(
                        fallback_domain=w or h,
                        fallback_url=url,
                    )
                    if extra_cookies:
                        await self._context.add_cookies(extra_cookies)
            except Exception as e:
                logger.debug("On-demand session injection notice: %s", e)

        try:
            # Prefer domcontentloaded for robust handling of heavy SPAs / tracking scripts
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            self.last_navigation_error = str(e)
            self.last_navigation_outcome = NavigationOutcome(
                target_url=url,
                status=NavigationStatus.ERROR_PAGE,
                error_message=str(e),
            )
            return 0

        try:
            await asyncio.sleep(wait_seconds)
            await self.check_and_handle_captcha()
        except Exception:
            pass

        # Evaluate navigation divergence telemetry
        landing_url = self.page.url
        page_title = ""
        try:
            page_title = await self.page.title()
        except Exception:
            pass

        orig_p = urlparse(url)
        land_p = urlparse(landing_url)
        redirected = (
            orig_p.netloc.lower() != land_p.netloc.lower()
            or orig_p.path.rstrip("/").lower() != land_p.path.rstrip("/").lower()
        )

        status = NavigationStatus.OK
        diag_hint = None

        auth_indicators = ("/login", "/signin", "/auth", "/cas/login", "/sso", "/oauth", "/passport", "/session/new")
        is_login_path = any(ind in land_p.path.lower() for ind in auth_indicators)
        has_auth_query = any(k in land_p.query.lower() for k in ("return_to=", "redirect_uri=", "next="))
        title_auth = any(term in page_title.lower() for term in ("sign in", "log in", "登录", "sign-in", "login"))
        orig_is_login = any(ind in orig_p.path.lower() for ind in auth_indicators)

        if (is_login_path or has_auth_query or title_auth) and not orig_is_login:
            status = NavigationStatus.AUTH_REDIRECT
            diag_hint = (
                f"[Auth Barrier Alert] Navigation to '{url}' was redirected to authentication endpoint "
                f"'{landing_url}' (Page Title: '{page_title}'). The target page requires an active, authenticated session. "
                f"Do NOT abandon the target, declare credentials unavailable, or drift to arbitrary public pages. "
                f"Inspect session credentials and cookie domain configuration."
            )
        elif self.last_resolved_captcha:
            status = NavigationStatus.BOT_CHALLENGE
        elif redirected:
            status = NavigationStatus.URL_DIVERGED

        self.last_navigation_outcome = NavigationOutcome(
            target_url=url,
            landing_url=landing_url,
            status=status,
            redirected=redirected,
            page_title=page_title,
            diagnostic_hint=diag_hint,
        )

        await self._capture_crypto_calls()
        return len(self.traffic_store.records) - before_count

    async def scroll(self, distance_px: int = 1000, times: int = 2) -> int:
        before_count = len(self.traffic_store.records)
        for _ in range(times):
            await self.page.evaluate(f"window.scrollBy(0, {distance_px})")
            await asyncio.sleep(1.2)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass
        return len(self.traffic_store.records) - before_count

    async def click(self, selector: str, wait_seconds: int = 2) -> Tuple[bool, str, int]:
        """Click an interactive element matching CSS selector and capture background traffic."""
        if not self.page:
            return False, "Browser page is not initialized.", 0
        before_count = len(self.traffic_store.records)
        try:
            locator = self.page.locator(selector).first
            await locator.wait_for(state="visible", timeout=8000)
            await locator.click(timeout=8000)
            await asyncio.sleep(wait_seconds)
            await self.check_and_handle_captcha()
            try:
                await self.page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass
            new_reqs = len(self.traffic_store.records) - before_count
            return True, f"Clicked '{selector}' successfully. Captured {new_reqs} new background traffic requests.", new_reqs
        except Exception as e:
            new_reqs = len(self.traffic_store.records) - before_count
            return False, f"Failed to click '{selector}': {str(e)[:200]}", new_reqs

    async def input_text(self, selector: str, text: str, press_enter: bool = True, wait_seconds: int = 3) -> Tuple[bool, str, int]:
        """Type text into an input field, optionally press Enter, and capture traffic."""
        if not self.page:
            return False, "Browser page is not initialized.", 0
        before_count = len(self.traffic_store.records)
        try:
            locator = self.page.locator(selector).first
            await locator.wait_for(state="visible", timeout=8000)
            await locator.fill(text, timeout=8000)
            if press_enter:
                await locator.press("Enter")
            await asyncio.sleep(wait_seconds)
            await self.check_and_handle_captcha()
            try:
                await self.page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass
            new_reqs = len(self.traffic_store.records) - before_count
            return True, f"Filled '{text}' into '{selector}' (press_enter={press_enter}). Captured {new_reqs} new background traffic requests.", new_reqs
        except Exception as e:
            new_reqs = len(self.traffic_store.records) - before_count
            return False, f"Failed to fill '{selector}': {str(e)[:200]}", new_reqs

    async def inspect_dom(self, selector: str, attributes: Optional[List[str]] = None, limit: int = 30) -> List[Dict[str, Any]]:
        """Extract structured data from DOM elements matching CSS selector."""
        if not self.page:
            return [{"error": "Browser page is not initialized."}]
        attrs = attributes or []
        js_code = """
        (args) => {
            const {selector, attributes, limit} = args;
            const elements = document.querySelectorAll(selector);
            const results = [];
            for (let i = 0; i < Math.min(elements.length, limit); i++) {
                const el = elements[i];
                const item = { _index: i, _tag: el.tagName.toLowerCase(), _text: el.innerText?.trim()?.substring(0, 200) || "" };
                for (const attr of attributes) {
                    item[attr] = el.getAttribute(attr) || "";
                }
                const links = el.querySelectorAll('a[href]');
                if (links.length > 0) {
                    item._links = Array.from(links).map(a => ({text: a.innerText?.trim(), href: a.href})).slice(0, 5);
                }
                results.push(item);
            }
            return results;
        }
        """
        try:
            results = await self.page.evaluate(js_code, {"selector": selector, "attributes": attrs, "limit": limit})
            return results
        except Exception as e:
            return [{"error": str(e)}]

    
    async def extract_session_cookies(self, domain: Optional[str] = None) -> Dict[str, str]:
        """Extract active cookies from current browser context, optionally filtered by domain."""
        if not self._context:
            return {}
        try:
            cookies = await self._context.cookies()
            res = {}
            for c in cookies:
                c_domain = c.get("domain", "")
                if domain and domain.lstrip(".") not in c_domain:
                    continue
                name = c.get("name")
                val = c.get("value")
                if name and val is not None:
                    res[name] = val
            return res
        except Exception:
            return {}

    async def export_session(self, target_path: Optional[str] = None) -> Any:
        """Export active cookies from current context as SessionBundle and persist to file."""
        if not self._context:
            return None
        try:
            from scrapeclaw.probe.session_manager import CookieItem, SessionBundle, save_session_bundle
            cookies = await self._context.cookies()
            items = [
                CookieItem(
                    name=c["name"],
                    value=c["value"],
                    domain=c.get("domain", ""),
                    path=c.get("path", "/"),
                    expires=c.get("expires"),
                    httpOnly=c.get("httpOnly", False),
                    secure=c.get("secure", False),
                    sameSite=c.get("sameSite", "Lax"),
                )
                for c in cookies
            ]
            cur_url = self.page.url if self.page else ""
            bundle = SessionBundle(
                domain=cur_url,
                cookies=items,
                description=f"Exported from active session ({cur_url})",
            )
            out_path = target_path or self.save_session_path
            if out_path:
                save_session_bundle(bundle, out_path)
            return bundle
        except Exception:
            return None

    async def _capture_crypto_calls(self):
        """Harvest client-side cryptographic and sign calls from page buffer."""
        if not self.page:
            return
        try:
            from scrapeclaw.crypto.js_hooker import extract_crypto_snapshots_from_page
            new_calls = await extract_crypto_snapshots_from_page(self.page)
            if new_calls:
                self.crypto_calls.extend(new_calls)
                if len(self.crypto_calls) > 300:
                    self.crypto_calls = self.crypto_calls[-300:]
        except Exception as e:
            logger.debug(f"Failed to capture crypto calls: {e}")

    def get_crypto_snapshots(self, filter_type: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
        """Retrieve recorded client-side cryptographic calls, optionally filtered by type."""
        calls = self.crypto_calls
        if filter_type:
            ft = filter_type.lower()
            calls = [c for c in calls if ft in c.call_type.lower() or ft in c.function_name.lower()]
        return [c.model_dump() for c in calls[-limit:]]

    async def close(self):
        if self.save_session_path:
            try:
                await self.export_session(self.save_session_path)
            except Exception:
                pass
        if self.page:
            await self.page.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
