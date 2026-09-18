from scrapeclaw.probe.captcha_detector import CaptchaChallenge
"""Tool Execution Manager & Dispatcher."""
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from scrapeclaw.traffic.store import TrafficStore
from scrapeclaw.probe.browser import BrowserProbe
from scrapeclaw.analyzer.distiller import distill_json_structure, score_json_match
from scrapeclaw.analyzer.diff_probe import prune_minimal_headers
from scrapeclaw.analyzer.pagination import infer_pagination_diff
from scrapeclaw.synthesizer.generator import (
    render_crawler_script,
    render_drission_script,
    render_scrapy_project,
    render_scaffold,
)
from scrapeclaw.synthesizer.ast_checker import (
    check_script_safety,
    check_script_imports,
    check_project_safety,
)
from scrapeclaw.gate.execution_gate import run_standalone_execution_gate
from scrapeclaw.engine.agent_state import AgentState
from scrapeclaw.engine.scope_guard import TargetScopeGuard

class ToolManager:
    def __init__(
        self,
        traffic_store: TrafficStore,
        browser_probe: BrowserProbe,
        output_dir: Path,
        custom_output_file: Optional[Path] = None,
        scope_guard: Optional[TargetScopeGuard] = None,
        target_engine: str = "httpx"
    ):
        self.traffic_store = traffic_store
        self.browser_probe = browser_probe
        self.output_dir = output_dir
        self.custom_output_file = custom_output_file
        self.scope_guard = scope_guard
        self.target_engine = (target_engine or "httpx").lower()

    async def execute_tool(self, state: AgentState, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "browser_navigate":
            url = args.get("url", "")
            wait_sec = args.get("wait_seconds", 3)

            # Target Scope Guard Check
            if self.scope_guard:
                in_scope, err_msg = self.scope_guard.check_navigation(url)
                if not in_scope:
                    state.add_correction_hint(err_msg)
                    return err_msg

            try:
                setattr(self.browser_probe, "last_navigation_error", None)
                new_reqs = await self.browser_probe.navigate(url, wait_seconds=wait_sec)
                nav_err = getattr(self.browser_probe, "last_navigation_error", None)
                if nav_err:
                    err_msg = f"Failed to navigate to {url}: {nav_err}. The page may be offline, blocking connections (e.g. net::ERR_CONNECTION_CLOSED), or unreachable."
                    state.add_correction_hint(err_msg)
                    return err_msg

                outcome = getattr(self.browser_probe, "last_navigation_outcome", None)
                if outcome and getattr(outcome, "status", None) and outcome.status.value == "AUTH_REDIRECT":
                    if outcome.diagnostic_hint:
                        state.add_correction_hint(outcome.diagnostic_hint)
                    msg = f"Navigated to {url} -> REDIRECTED to authentication endpoint ({outcome.landing_url})! [Auth Required: Valid session credentials needed]"
                elif outcome and outcome.redirected and getattr(outcome, "status", None) and outcome.status.value in ("OK", "URL_DIVERGED"):
                    msg = f"Navigated to {url} (landed on {outcome.landing_url}). Captured {new_reqs} new background traffic requests."
                else:
                    msg = f"Navigated to {url}. Captured {new_reqs} new background traffic requests."

                chal = getattr(self.browser_probe, "last_resolved_captcha", None)
                if chal is not None and isinstance(chal, CaptchaChallenge):
                    self.browser_probe.last_resolved_captcha = None
                    state.captcha_challenges_resolved += 1
                    state.pin_fact("captcha_resolved", f"Resolved {chal.challenge_type.value}: {chal.details}")
                    msg += f" [Captcha Bypassed: {chal.challenge_type.value}]"
                return msg
            except Exception as e:
                err_msg = f"Navigation error on {url}: {str(e)[:200]}"
                state.add_correction_hint(err_msg)
                return err_msg

        elif tool_name == "browser_scroll":
            dist = args.get("distance_px", 1000)
            times = args.get("times", 2)
            new_reqs = await self.browser_probe.scroll(distance_px=dist, times=times)
            return f"Scrolled down {times} times ({dist}px). Captured {new_reqs} new background requests."

        elif tool_name == "browser_click":
            selector = args.get("selector", "")
            wait_sec = args.get("wait_seconds", 2)
            ok, msg, new_reqs = await self.browser_probe.click(selector, wait_seconds=wait_sec)
            if ok:
                state.pin_fact("interaction", f"Clicked '{selector}' -> {new_reqs} new requests")
                # Advance execution plan if in VIEW_ALIGNMENT
                if hasattr(state, "execution_plan") and state.execution_plan:
                    from scrapeclaw.engine.planner import ScrapePhase
                    state.execution_plan.advance_to_phase(ScrapePhase.API_REVERSE)
            chal = getattr(self.browser_probe, "last_resolved_captcha", None)
            if chal is not None and isinstance(chal, CaptchaChallenge):
                self.browser_probe.last_resolved_captcha = None
                state.captcha_challenges_resolved += 1
                state.pin_fact("captcha_resolved", f"Resolved {chal.challenge_type.value}: {chal.details}")
                msg += f" [Captcha Bypassed: {chal.challenge_type.value}]"
            return msg

        elif tool_name == "browser_input":
            selector = args.get("selector", "")
            text = args.get("text", "")
            press_enter = args.get("press_enter", True)
            wait_sec = args.get("wait_seconds", 3)
            ok, msg, new_reqs = await self.browser_probe.input_text(selector, text, press_enter=press_enter, wait_seconds=wait_sec)
            if ok:
                state.pin_fact("interaction", f"Input '{text}' into '{selector}' -> {new_reqs} new requests")
            return msg

        elif tool_name == "browser_inspect_dom":
            selector = args.get("selector", "")
            attributes = args.get("attributes", [])
            limit = args.get("limit", 30)
            elements = await self.browser_probe.inspect_dom(selector, attributes, limit)
            if not elements:
                return f"No elements matched selector: {selector}"
            preview = json.dumps(elements[:5], ensure_ascii=False, indent=2)[:1500]
            state.pin_fact("dom_structure", f"Matched {len(elements)} elements with '{selector}'")
            res_text = f"Matched {len(elements)} DOM elements with '{selector}'.\nFirst 5 elements:\n{preview}"

            # Intelligent Category Navigation Sniffing
            goal_spec = getattr(state, "goal_spec", None)
            if goal_spec and goal_spec.filter_keywords:
                from scrapeclaw.analyzer.dom_nav_sniffer import sniff_category_navigation, format_category_navigation_hint
                raw_dom_text = json.dumps(elements, ensure_ascii=False)
                candidates = sniff_category_navigation(raw_dom_text, goal_spec.filter_keywords)
                hint = format_category_navigation_hint(candidates)
                if hint:
                    res_text += f"\n\n{hint}"

            return res_text

        elif tool_name == "traffic_list":
            only_cand = args.get("only_candidates", True)
            limit = args.get("limit", 10)
            records = self.traffic_store.records[-30:]
            out = []
            goal_kws = [w.strip() for w in state.goal_description.split() if len(w.strip()) > 1]
            
            for r in reversed(records):
                if not r.response or r.response.status_code != 200:
                    continue
                raw_b = self.traffic_store.read_raw_response(r)
                if not raw_b:
                    continue
                try:
                    data = json.loads(raw_b)
                    score, matched, data_path = score_json_match(data, goal_kws)
                    r.match_score = score
                    r.matched_keys = matched
                    if only_cand and score < 0.2:
                        continue
                    out.append(f"- {r.id}: {r.request.method} {r.request.url[:80]} (Match={score:.0%}, keys={matched}, len={r.response.body_length}B)")
                except Exception:
                    continue
                if len(out) >= limit:
                    break
            return "\n".join(out) if out else "No candidate API traffic found yet. Try scrolling or interacting."

        elif tool_name == "traffic_inspect":
            t_id = args.get("traffic_id", "")
            rec = self.traffic_store.get_record(t_id)
            if not rec:
                return f"Traffic record {t_id} not found."
            raw_b = self.traffic_store.read_raw_response(rec)
            try:
                data = json.loads(raw_b)
                distilled = distill_json_structure(data)
                preview = json.dumps(distilled, ensure_ascii=False, indent=2)[:1500]
                state.pin_fact("candidate_api", f"{rec.request.method} {rec.request.url}", traffic_id=t_id)
                return f"=== Traffic {t_id} ===\nURL: {rec.request.url}\nDistilled Schema:\n{preview}"
            except Exception as e:
                return f"Failed to parse JSON for {t_id}: {e}"

        elif tool_name == "diff_probe_headers":
            t_id = args.get("traffic_id", "")
            rec = self.traffic_store.get_record(t_id)
            if not rec:
                return f"Traffic record {t_id} not found."
            min_h, min_c = await prune_minimal_headers(
                rec.request.url,
                rec.request.method,
                rec.request.headers,
                rec.request.cookies,
                rec.request.json_body
            )
            state.pin_fact("minimal_headers", json.dumps(min_h, ensure_ascii=False), traffic_id=t_id)
            return f"Pruned headers successfully! Kept {len(min_h)} headers (from {len(rec.request.headers)}), {len(min_c)} cookies. Required headers: {list(min_h.keys())}"

        elif tool_name == "inspect_js_crypto":
            filter_type = args.get("filter_type")
            limit = int(args.get("limit", 20))
            if hasattr(self.browser_probe, "_capture_crypto_calls"):
                await self.browser_probe._capture_crypto_calls()
            if hasattr(self.browser_probe, "get_crypto_snapshots"):
                snapshots = self.browser_probe.get_crypto_snapshots(filter_type=filter_type, limit=limit)
            else:
                snapshots = []
            if not snapshots:
                return f"No client-side JavaScript cryptographic calls captured yet matching filter '{filter_type or 'all'}'. Try navigating or triggering user interactions (click, input) first."
            return json.dumps(snapshots, indent=2, ensure_ascii=False)

        elif tool_name == "execute_js_snippet":
            code = args.get("code", "")
            if not code.strip():
                return "Error: Empty code provided to execute_js_snippet."
            context_vars = args.get("context_vars") or {}
            expected_output = args.get("expected_output")
            use_browser_rpc = bool(args.get("use_browser_rpc", False))

            if use_browser_rpc:
                if not self.browser_probe or not getattr(self.browser_probe, "page", None):
                    return "Error: Browser page not available for RPC execution."
                from scrapeclaw.crypto.browser_rpc import BrowserRPCBridge
                bridge = BrowserRPCBridge(self.browser_probe.page)
                ok, msg, result = await bridge.evaluate_signature(code, context_vars)
                if not ok:
                    return f"[RPC_EXEC_FAIL] {msg}"
            else:
                from scrapeclaw.crypto.js_runner import JSRuntime
                runtime = JSRuntime()
                if not runtime.is_available():
                    return "Error: Node.js runtime not found in PATH. Ensure Node.js is installed."

                ok, msg, result = await runtime.execute_code(code, context_vars=context_vars, timeout=5.0)
                if not ok:
                    return f"[JS_EXEC_FAIL] {msg}"

            result_str = str(result)
            match_info = ""
            if expected_output is not None:
                expected_str = str(expected_output).strip()
                actual_str = result_str.strip()
                if actual_str == expected_str:
                    match_info = f"\n[ASSERTION_PASSED] Output perfectly matches expected: '{expected_str}'"
                    state.pin_fact("js_signature_verified", f"Snippet verified with expected output: {expected_str}")
                else:
                    match_info = f"\n[ASSERTION_FAILED] Output mismatch!\nExpected: {expected_str}\nActual:   {actual_str}"

            rendered = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else result_str
            return f"[JS_EXEC_SUCCESS] Result: {rendered}{match_info}"

        elif tool_name == "infer_pagination":
            b_id = args.get("base_traffic_id", "")
            n_id = args.get("next_traffic_id", "")
            b_rec = self.traffic_store.get_record(b_id)
            n_rec = self.traffic_store.get_record(n_id)
            if not b_rec or not n_rec:
                return "Records not found."
            param, step, kind = infer_pagination_diff(b_rec.request.query_params, n_rec.request.query_params)
            state.pin_fact("pagination", f"param={param}, step={step}, kind={kind}")
            return f"Pagination inferred: parameter='{param}', step={step}, type='{kind}'"

        elif tool_name in ("synthesize_crawler", "synthesize_crawler_script"):
            cookies = args.get("minimal_cookies", {})
            if not cookies and hasattr(self.browser_probe, "extract_session_cookies"):
                try:
                    live_cookies = await self.browser_probe.extract_session_cookies()
                    if live_cookies:
                        cookies = live_cookies
                except Exception:
                    pass
            bundle = getattr(self.browser_probe, "session_bundle", None)
            if not cookies and bundle and not bundle.is_empty():
                cookies = bundle.to_httpx_cookies()

            spec = {
                "target_url": state.target_url or args.get("target_url", ""),
                "target_api_url": args.get("target_api_url", ""),
                "method": args.get("method", "GET"),
                "minimal_headers": args.get("minimal_headers", {}),
                "minimal_cookies": cookies,
                "query_params": args.get("query_params", {}),
                "pagination_param": args.get("pagination_param", "page"),
                "pagination_step": args.get("pagination_step", 1),
                "data_jsonpath": args.get("data_jsonpath", "data"),
                "sign_js_code": args.get("sign_js_code", ""),
                "sign_header_name": args.get("sign_header_name", ""),
                "sign_param_name": args.get("sign_param_name", ""),
                "sample_data": getattr(state, "verified_sample_data", []),
                "project_name": args.get("project_name", "scrapeclaw_project"),
                "spider_name": args.get("spider_name", "target_spider"),
            }

            if self.target_engine == "scrapy":
                if self.custom_output_file:
                    project_base = self.custom_output_file.parent / (self.custom_output_file.stem + "_scrapy")
                else:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    project_base = self.output_dir / "scrapeclaw_project"

                created = render_scrapy_project(spec, project_base)
                # Find project root containing scrapy.cfg
                actual_root = created["scrapy.cfg"].parent if "scrapy.cfg" in created else project_base
                safe, reason = check_project_safety(actual_root)
                if not safe:
                    return f"Scrapy Project AST Safety Check Failed: {reason}"
                state.synthesized_code_path = str(actual_root)
                state.pin_fact("synthesized_engine", "scrapy", traffic_id="")
                return (
                    f"Scrapy industrial project scaffolded successfully at {project_base} "
                    f"({len(created)} files created: scrapy.cfg, settings.py, items.py, middlewares.py, pipelines.py, spiders/target_spider.py)! "
                    f"Next, MUST call execute_crawler_sandbox to verify."
                )

            elif self.target_engine in ("drission", "drissionpage"):
                if self.custom_output_file:
                    out_path = self.custom_output_file
                else:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    out_path = self.output_dir / "drission_spider.py"

                code = render_drission_script(spec)
                safe, reason = check_script_safety(code)
                if not safe:
                    return f"AST Safety Check Failed: {reason}"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(code, encoding="utf-8")
                state.synthesized_code_path = str(out_path)
                state.pin_fact("synthesized_engine", "drission", traffic_id="")
                return f"DrissionPage crawler synthesized successfully at {out_path}! Next, MUST call execute_crawler_sandbox to verify."

            else:
                code = render_crawler_script(spec)
                safe, reason = check_script_safety(code)
                if not safe:
                    return f"AST Safety Check Failed: {reason}"
                
                if self.custom_output_file:
                    out_path = self.custom_output_file
                else:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    out_path = self.output_dir / "generated_spider.py"

                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(code, encoding="utf-8")
                state.synthesized_code_path = str(out_path)
                state.pin_fact("synthesized_engine", "httpx", traffic_id="")
                return f"Crawler synthesized successfully at {out_path}! Next, MUST call execute_crawler_sandbox to verify."

        elif tool_name == "write_custom_crawler":
            code = args.get("code", "")
            description = args.get("description", "")
            auxiliary_files = args.get("auxiliary_files") or {}
            
            if not code.strip():
                return "Error: Empty code provided."
            
            # AST safety check
            safe, reason = check_script_safety(code)
            if not safe:
                return f"AST Safety Check Failed: {reason}. Fix the blocked calls and retry."
            
            # AST import whitelist check (Pre-flight check)
            imports_ok, import_reason = check_script_imports(code)
            if not imports_ok:
                state.add_correction_hint(f"Pre-flight Check Failed: {import_reason}")
                return f"Import Pre-flight Check Failed: {import_reason}"

            # Basic contract check: must import httpx, must have json.dumps or json.dump
            if "import httpx" not in code:
                return "Contract Violation: Custom crawler must use httpx for HTTP requests (must contain 'import httpx')."
            if "json.dumps" not in code and "json.dump" not in code:
                return "Contract Violation: Custom crawler must output JSON to stdout (must contain 'json.dumps' or 'json.dump')."
            
            # Write to output path
            if self.custom_output_file:
                out_path = self.custom_output_file
            else:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                out_path = self.output_dir / "generated_spider.py"
            
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(code, encoding="utf-8")

            # Write any auxiliary files (e.g. sign.js)
            written_aux = []
            if isinstance(auxiliary_files, dict):
                for aux_name, aux_content in auxiliary_files.items():
                    aux_path = out_path.parent / aux_name
                    aux_path.write_text(str(aux_content), encoding="utf-8")
                    written_aux.append(aux_name)

            state.synthesized_code_path = str(out_path)
            aux_msg = f" (alongside: {', '.join(written_aux)})" if written_aux else ""
            state.pin_fact("custom_crawler", f"Custom crawler written: {description}{aux_msg}", traffic_id="")
            return f"Custom crawler written to {out_path}{aux_msg}. Strategy: {description}. MUST call execute_crawler_sandbox to verify."

        elif tool_name == "execute_crawler_sandbox":
            script_p = args.get("script_path") or state.synthesized_code_path
            if not script_p:
                return "No script path provided."
            ok, msg, data = await run_standalone_execution_gate(script_p)
            state.verification_passed = ok
            if ok:
                state.verified_sample_data = data
                state.pin_fact("verified_crawler", f"Verified script at {script_p} extracted {len(data)} items")
            return msg

        return f"Unknown tool: {tool_name}"
