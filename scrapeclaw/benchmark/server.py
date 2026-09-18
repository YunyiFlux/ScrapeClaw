# -*- coding: utf-8 -*-
"""Embedded Mock Server for ScrapeEval-50 Reproducible Offline Benchmark."""
import json
import threading
import hashlib
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional


class BenchmarkRequestHandler(BaseHTTPRequestHandler):
    """Handles mock endpoints across all 7 benchmark categories."""

    def log_message(self, format, *args):
        # Silence default stderr logging
        pass

    def _send_json(self, data: dict or list, status: int = 200, headers: dict = None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # 1. Category: Pagination
        if "/mock/pagination/page_step" in path:
            page = int(qs.get("page", [1])[0])
            items = [{"id": (page - 1) * 3 + i, "title": f"Book Page {page} - {i}", "price": 29.9 + i} for i in range(1, 4)]
            self._send_json({"code": 0, "page": page, "data": {"items": items}})
            return

        if "/mock/pagination/offset_limit" in path:
            offset = int(qs.get("offset", [0])[0])
            limit = int(qs.get("limit", [10])[0])
            items = [{"title": f"News Headline #{offset + i}", "date": "2026-09-18", "views": 100 * (offset + i)} for i in range(limit)]
            self._send_json({"total": 100, "data": items})
            return

        if "/mock/pagination/cursor" in path:
            cursor = qs.get("cursor", ["start"])[0]
            next_cursor = "token_page_2" if cursor == "start" else ("token_page_3" if cursor == "token_page_2" else "")
            items = [{"title": f"Post cursor={cursor} item {i}", "author": f"User_{i}"} for i in range(3)]
            self._send_json({"items": items, "next_cursor": next_cursor})
            return

        # 2. Category: Navigation
        if "/mock/nav/tabs" in path:
            cat = qs.get("category", ["all"])[0]
            html = f"""<!DOCTYPE html>
            <html>
            <head><title>Tab Portal</title></head>
            <body>
              <div class="tabs">
                <a href="?category=tech" id="tab-tech" class="tab">科技数码</a>
                <a href="?category=all" id="tab-all" class="tab">全部</a>
              </div>
              <ul id="items">
                <li>Book Tech 1</li>
                <li>Book Tech 2</li>
                <li>Book Tech 3</li>
              </ul>
            </body>
            </html>"""
            self._send_html(html)
            return

        # 3. Category: Unpacking
        if "/mock/unpack/root_array" in path:
            items = [{"id": i, "title": f"Root Product {i}", "price": 49.0 + i} for i in range(1, 6)]
            self._send_json(items)
            return

        if "/mock/unpack/graphql_edges" in path:
            edges = [
                {"node": {"title": f"GraphQL Post {i}", "author": f"Dev_{i}"}}
                for i in range(1, 5)
            ]
            self._send_json({"data": {"posts": {"edges": edges}}})
            return

        if "/mock/unpack/single_profile" in path:
            self._send_json({"code": 0, "data": {"username": "AntigravityUser", "uid": 1234567, "followers": 8888}})
            return

        # 4. Category: Auth & Session
        if "/mock/auth/" in path:
            cookie_header = self.headers.get("Cookie", "")
            auth_header = self.headers.get("Authorization", "")
            if "auth_token" in cookie_header or "Bearer" in auth_header:
                self._send_json({"code": 0, "user_id": 99999, "assets": 500, "role": "vip", "session_ok": True, "uid": 99999, "parsed_ok": True, "exported": True, "active_account": "admin", "level": 6})
            else:
                self._send_json({"error": "Unauthorized", "message": "Missing session cookie or token"}, status=401)
            return

        # 5. Category: Anti-Scraping
        if "/mock/anti/referer_guard" in path:
            referer = self.headers.get("Referer", "")
            if not referer:
                self._send_json({"error": "Forbidden", "message": "Missing Referer anti-hotlink"}, status=403)
                return
            items = [{"title": f"Protected Item {i}", "price": 100 * i} for i in range(1, 5)]
            self._send_json({"code": 0, "items": items})
            return

        if "/mock/anti/md5_signature" in path:
            sign = qs.get("sign", [""])[0]
            if not sign:
                self._send_json({"error": "Signature mismatch", "message": "sign parameter required"}, status=403)
                return
            items = [{"item_id": 100 + i, "title": f"Signed Product {i}"} for i in range(3)]
            self._send_json({"status": "ok", "items": items})
            return

        # 6. Category: Captcha
        if "/mock/captcha/turnstile" in path:
            # Renders Cloudflare's official interactive test widget (3x00000000000000000000FF forces visible checkbox)
            html = """<!DOCTYPE html>
            <html>
            <head>
              <title>Turnstile Test Portal</title>
              <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
            </head>
            <body>
              <h2>Cloudflare Turnstile Protected Data Portal</h2>
              <div id="verified-status">Waiting for verification...</div>
              <div class="cf-turnstile" data-sitekey="3x00000000000000000000FF" data-callback="onSuccess"></div>
              <script>
                function onSuccess(token) {
                  document.getElementById('verified-status').innerText = 'Verified! Token: ' + token;
                  fetch('/mock/captcha/turnstile/data?token=' + encodeURIComponent(token));
                }
              </script>
            </body>
            </html>"""
            self._send_html(html)
            return

        if "/mock/captcha/turnstile/data" in path:
            self._send_json({"code": 0, "status": "success", "message": "Turnstile bypassed successfully", "data": [{"id": 1, "secret_content": "Protected Payload Unlocked"}]})
            return

        if "/mock/captcha/geetest" in path:
            html = """<!DOCTYPE html>
            <html>
            <head><title>安全验证</title></head>
            <body>
              <div class="geetest_holder">
                <div class="geetest_radar_tip">点击按钮验证</div>
                <div class="geetest_slider"></div>
              </div>
            </body>
            </html>"""
            self._send_html(html)
            return

        # Generic Mock Fallback for any task
        items = [{"id": i, "title": f"Generic Mock Item {i}", "price": 99.0, "status": "ok", "content": "mock content", "bom_present": True, "files_count": 6, "ast_valid": True, "syntax_valid": True, "lines_count": 5} for i in range(1, 5)]
        self._send_json({"code": 0, "status": "ok", "data": {"items": items}, "items": items})


class BenchmarkServer:
    """Threaded HTTP Server for offline deterministic ScrapeEval-50 execution."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.requested_port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port = port

    def start(self) -> str:
        self.server = HTTPServer((self.host, self.requested_port), BenchmarkRequestHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.get_base_url()

    def get_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            self.thread = None
