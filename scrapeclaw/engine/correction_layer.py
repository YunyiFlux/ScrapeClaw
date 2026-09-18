from urllib.parse import urlparse
"""Enhanced Correction Layer & Stall Guards with Anti-Scraping Diagnosis."""
import re
from typing import List, Optional
from scrapeclaw.engine.agent_state import AgentState



def check_goal_quantity_mismatch(goal: str, items_count: int) -> Optional[str]:
    """Check if extracted items count violates goal constraints using GoalSpec and ConstraintPolicy.
    
    Delegates to ScrapeClaw's structured constraint policy framework.
    """
    if items_count <= 1 and not goal:
        return None

    from scrapeclaw.analyzer.goal_parser import parse_goal_spec
    from scrapeclaw.engine.constraint_policy import validate_extracted_data

    spec = parse_goal_spec(goal)
    dummy_data = [{"dummy": i} for i in range(items_count)]
    violations = validate_extracted_data(dummy_data, spec)
    for v in violations:
        if v.kind == "cardinality_mismatch":
            return v.to_prompt_hint()
    return None

class CorrectionLayer:
    def __init__(self):
        # Track 1: Identical tool call repetition
        self.last_tool_signature = ""
        self.repeated_tool_count = 0
        
        # Track 2: Consecutive empty/stall results
        self.consecutive_stalls = 0
        
        # Track 3: Synthesis-Gate failure loop
        self.synthesis_count = 0
        self.gate_failure_count = 0
        self.gate_zero_items_streak = 0
        
        # Track 4: Same-tool-name repetition (regardless of args)
        self.last_tool_name = ""
        self.same_tool_name_count = 0

    def check_pre_tool(self, state: AgentState, tool_name: str, args: dict) -> Optional[str]:
        # --- Check 1: Exact-signature repetition ---
        sig = f"{tool_name}::{sorted(args.items())}"
        if sig == self.last_tool_signature:
            self.repeated_tool_count += 1
            if self.repeated_tool_count >= 2:
                hint = (
                    f"Loop Alert: You called {tool_name} with identical arguments "
                    f"{self.repeated_tool_count + 1} times. Try a fundamentally different approach."
                )
                state.add_correction_hint(hint)
                return hint
        else:
            self.repeated_tool_count = 0
            self.last_tool_signature = sig
        
        # --- Check 2: Same tool name called repeatedly (even with different args) ---
        if tool_name == self.last_tool_name:
            self.same_tool_name_count += 1
            if self.same_tool_name_count >= 3 and tool_name == "synthesize_crawler":
                hint = (
                    "Pattern Alert: You have called synthesize_crawler 3+ times consecutively. "
                    "The standard template likely cannot handle this API pattern. "
                    "Use write_custom_crawler to generate a fully custom Python script instead."
                )
                state.add_correction_hint(hint)
                self.same_tool_name_count = 0
                return hint
        else:
            self.same_tool_name_count = 1
            self.last_tool_name = tool_name
        
        # --- Track synthesis attempts ---
        if tool_name == "synthesize_crawler":
            self.synthesis_count += 1

        # --- Check 3: Plan Guard & Skip-Ahead Reflexion ---
        if tool_name in ("synthesize_crawler", "write_custom_crawler"):
            plan = getattr(state, "execution_plan", None)
            if plan and plan.requires_view_alignment and not plan.is_alignment_completed():
                goal_spec = getattr(state, "goal_spec", None)
                cat_kws = goal_spec.filter_keywords if goal_spec else []
                cat_str = ", ".join(cat_kws) if cat_kws else "target category"
                hint = (
                    f"[Plan Guard Alert] Plan Step 2 (VIEW_ALIGNMENT) is NOT completed! "
                    f"The user goal explicitly requires '{cat_str}', but you have not navigated to or clicked the category tab in the page. "
                    f"Synthesizing now will extract the broad all-category feed and mix non-target items! "
                    f"Action: Use browser_inspect_dom to locate the '{cat_str}' tab/button and call browser_click first."
                )
                state.add_correction_hint(hint)
                return hint

        # --- Check 4: Target Invariance & Anti-Drift Guard ---
        invariance_alert = self.check_target_invariance(state, tool_name, args)
        if invariance_alert:
            return invariance_alert

        return None

    def check_target_invariance(self, state: AgentState, tool_name: str, args: dict) -> Optional[str]:
        """Verify that synthesized crawler code adheres to the user's immutable target contract.
        
        Guards against:
        1. Arbitrary placeholder entity substitution (e.g. DEFAULT_USERNAMES = ["github", ...]).
        2. Target endpoint / path abandonment (e.g. discarding /settings/profile and targeting unauthenticated public index).
        3. Unauthenticated downgrade when active session credentials exist.
        """
        if tool_name not in ("write_custom_crawler", "synthesize_crawler"):
            return None

        target_url = state.target_url or ""
        parsed_target = urlparse(target_url)
        target_path = parsed_target.path.strip("/").lower()

        # Check if target is a private / personal / authenticated resource
        is_private_target = (
            any(k in target_path for k in ("settings", "profile", "account", "user/", "dashboard", "order", "admin", "my", "inbox", "cart"))
            or getattr(state, "has_auth_session", False)
            or state.has_fact_type("auth_session")
        )

        code = args.get("code", "") if tool_name == "write_custom_crawler" else args.get("target_api_url", "")
        code_lower = code.lower()

        # Check 1: Anti-Placeholder / Entity Substitution
        placeholder_patterns = [
            r"\bdefault_usernames\s*=\s*\[",
            r"\bdefault_accounts\s*=\s*\[",
            r"\bsample_users\s*=\s*\[",
            r"\bmock_users\s*=\s*\[",
            r"\btest_accounts\s*=\s*\[",
            r"\[\s*['\"]github['\"]\s*,\s*['\"]torvalds['\"]",
            r"\[\s*['\"]admin['\"]\s*,\s*['\"]test['\"]",
        ]
        for pat in placeholder_patterns:
            if re.search(pat, code_lower):
                hint = (
                    f"[Target Drift Alert] Target drift detected! Your proposed crawler script defines arbitrary fallback "
                    f"entity lists (matching '{pat}') instead of extracting from the requested target. "
                    f"The user's requested target is '{target_url}'. When crawling personal center or settings, you MUST crawl "
                    f"the user's own profile using the active session credentials. Do NOT substitute arbitrary public entities."
                )
                state.add_correction_hint(hint)
                return hint

        # Check 2: Target Path & Scope Abandonment
        if is_private_target and target_path:
            first_segment = target_path.split("/")[0]
            if first_segment not in code_lower and ("base_url" in code_lower or "url =" in code_lower):
                if "/{username}" in code_lower or "/{user}" in code_lower or "github.com/{}" in code_lower:
                    hint = (
                        f"[Target Drift Alert] Target endpoint abandonment detected! The requested target is '{target_url}', "
                        f"which points to protected resource '{target_path}'. Your crawler code abandons this path and targets "
                        f"an unauthenticated public endpoint (e.g. /{{username}}). If authentication is required, you must "
                        f"scrape the protected target using the provided session cookies."
                    )
                    state.add_correction_hint(hint)
                    return hint

        # Check 3: Unauthenticated Downgrade on Authenticated Session
        if (getattr(state, "has_auth_session", False) or state.has_fact_type("auth_session") or is_private_target) and tool_name == "write_custom_crawler":
            has_cookies_arg = "cookies=" in code
            has_cookie_header = "'cookie'" in code_lower or '"cookie"' in code_lower
            has_auth_header = "authorization" in code_lower or "'token'" in code_lower or '"token"' in code_lower
            if "httpx.client" in code_lower and not (has_cookies_arg or has_cookie_header or has_auth_header):
                hint = (
                    f"[Auth Integrity Alert] The target '{target_url}' requires authentication and an active session was loaded, "
                    f"but your custom crawler script makes requests without passing session cookies or auth headers. "
                    f"You must include session cookies (e.g. httpx.Client(cookies=...)) to access the protected data."
                )
                state.add_correction_hint(hint)
                return hint

        return None

    def check_post_tool(self, state: AgentState, tool_name: str, result_summary: str):
        # --- Check 3: Generic stall detection ---
        if "0 new requests" in result_summary or "No candidate" in result_summary:
            self.consecutive_stalls += 1
            if self.consecutive_stalls >= 3:
                state.add_correction_hint(
                    "Stall Guard: Recent actions produced no new data. "
                    "Consider: (1) clicking specific page elements, "
                    "(2) inspecting existing traffic with only_candidates=False, "
                    "(3) using browser_inspect_dom to parse HTML directly."
                )
        else:
            self.consecutive_stalls = 0
        
        # --- Check 4: Synthesis-Gate failure loop & Track 5 Anti-Scraping Diagnosis ---
        if tool_name == "execute_crawler_sandbox":
            is_zero_items = bool(re.search(r"\b0 items\b", result_summary, re.IGNORECASE) or "empty array" in result_summary.lower() or "[0_ITEMS]" in result_summary)
            is_success = "passed" in result_summary.lower() and not is_zero_items
            
            # Anti-Scraping Diagnosis: 403 Forbidden
            if "[403_FORBIDDEN]" in result_summary or "403 forbidden" in result_summary.lower() or "403" in result_summary:
                hint = (
                    "[Anti-Scraping Alert] 403 Forbidden detected during sandbox execution! "
                    "This indicates anti-hotlinking or origin protection. "
                    f"Action: (1) In minimal_headers, re-attach 'Referer': '{state.target_url}' and standard Chrome 'User-Agent'. "
                    "(2) Check traffic_inspect to see if session Cookies or 'Origin' headers are required."
                )
                state.add_correction_hint(hint)
                self.gate_failure_count += 1
                return

            # Anti-Scraping Diagnosis: 429 Too Many Requests
            if "[429_RATE_LIMIT]" in result_summary or "429" in result_summary or "too many requests" in result_summary.lower():
                hint = (
                    "[Rate-Limit Alert] 429 Too Many Requests detected during sandbox execution! "
                    "The target API is rate-limiting requests. "
                    "Action: Lower concurrency to 1 (concurrency=1) and add a 1.0~2.0s sleep between requests in your crawler."
                )
                state.add_correction_hint(hint)
                self.gate_failure_count += 1
                return

            # Anti-Scraping Diagnosis: 401 Unauthorized
            if "[401_UNAUTHORIZED]" in result_summary or "401 unauthorized" in result_summary.lower() or "401" in result_summary:
                hint = (
                    "[Auth Alert] 401 Unauthorized detected! "
                    "Endpoint requires authentication tokens or session cookies. "
                    "Action: Inspect minimal_headers / cookies from traffic_inspect and ensure auth headers are included."
                )
                state.add_correction_hint(hint)
                self.gate_failure_count += 1
                return

            # Entity Drift Diagnosis (Quality Check 3)
            if "[ENTITY_DRIFT]" in result_summary or "entity_drift" in result_summary.lower():
                hint = (
                    "[Entity Drift Alert] Sandbox execution rejected output because the crawler extracted arbitrary "
                    "public fallback entities rather than the target user's authentic data. "
                    "Action: Update the crawler script to request the protected target endpoint using active session cookies."
                )
                state.add_correction_hint(hint)
                self.gate_failure_count += 1
                return

            # Track 6: Dynamic Signature Failure Diagnosis
            from scrapeclaw.analyzer.signature_sniffer import is_signature_mismatch_error
            if is_signature_mismatch_error(result_summary):
                hint = (
                    "[Signature Alert] Dynamic signature verification failure detected! "
                    "The target API employs dynamic cryptographic signing (e.g. timestamp + query salt). "
                    "Action: (1) Inspect traffic_inspect to see if 'sign', 'token', or timestamp parameters are present. "
                    "(2) Use write_custom_crawler to implement dynamic signature calculation in Python."
                )
                state.add_correction_hint(hint)
                self.gate_failure_count += 1
                return

            if is_zero_items:
                self.gate_zero_items_streak += 1
                self.gate_failure_count += 1
                
                if self.gate_zero_items_streak >= 2:
                    hint = (
                        "Gate Failure Loop: execute_crawler_sandbox returned 0 items "
                        f"{self.gate_zero_items_streak} times consecutively. "
                        "The standard synthesize_crawler template does NOT fit this API pattern. "
                        "Common mismatches: (1) Two-stage ID-to-detail APIs require fetching an ID list "
                        "then concurrently requesting each item endpoint. (2) Cursor pagination where "
                        "next_cursor is extracted from the previous response. "
                        "Action: Use write_custom_crawler to output a complete custom Python script "
                        "that handles the specific API flow you've discovered."
                    )
                    state.add_correction_hint(hint)
            elif is_success:
                self.gate_zero_items_streak = 0
                self.gate_failure_count = 0
                
                # Track 7: Goal Alignment & Semantic Constraint Policy Check
                from scrapeclaw.engine.constraint_policy import validate_extracted_data
                data_to_check = state.verified_sample_data
                if not data_to_check:
                    m_items = re.search(r"Extracted (\d+) items", result_summary)
                    if m_items:
                        cnt = int(m_items.group(1))
                        data_to_check = [{"item": i} for i in range(cnt)]
                
                if data_to_check:
                    violations = validate_extracted_data(data_to_check, getattr(state, "goal_spec", None))
                    for v in violations:
                        state.add_correction_hint(v.to_prompt_hint())
