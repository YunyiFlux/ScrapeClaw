"""Model-Led Autonomous Solve Loop for ScrapeClaw."""
import asyncio
import json
from pathlib import Path
from typing import Optional, Callable
from scrapeclaw.engine.agent_state import AgentState
from scrapeclaw.engine.prompts import SYSTEM_PROMPT, build_dynamic_system_prompt, build_round_context
from scrapeclaw.engine.correction_layer import CorrectionLayer
from scrapeclaw.engine.tool_manager import ToolManager
from scrapeclaw.engine.llm_client import LLMClient
from scrapeclaw.docs_tools import TOOLS_SCHEMA

class AgentSolver:
    def __init__(
        self,
        llm_client: LLMClient,
        tool_manager: ToolManager,
        max_steps: int = 25,
        on_event: Optional[Callable[[str, dict], None]] = None
    ):
        self.llm_client = llm_client
        self.tool_manager = tool_manager
        self.max_steps = max_steps
        self.correction_layer = CorrectionLayer()
        self.on_event = on_event

    def emit(self, kind: str, payload: dict):
        if self.on_event:
            self.on_event(kind, payload)

    async def solve(self, target_url: str, goal: str) -> AgentState:
        state = AgentState(target_url=target_url, goal_description=goal)

        # Auto-ground active session credentials into AgentState facts and prompt
        probe = getattr(self.tool_manager, "browser_probe", None)
        if probe and getattr(probe, "session_file", None):
            state.has_auth_session = True
            bundle = getattr(probe, "session_bundle", None)
            cookie_names = [c.name for c in bundle.cookies] if bundle else []
            dom = getattr(probe, "target_domain", "")
            state.pin_fact(
                "auth_session",
                f"Authenticated session loaded from '{probe.session_file}' for domain '{dom}' "
                f"(cookies: {', '.join(cookie_names) if cookie_names else 'active'}). "
                f"Target is authenticated. Standalone crawlers must preserve session credentials. "
                f"Target drift to public fallback accounts is strictly forbidden.",
            )

        dynamic_system = build_dynamic_system_prompt(
            getattr(state, "goal_spec", None),
            target_url,
            has_auth_session=state.has_auth_session,
        )
        messages = [
            {"role": "system", "content": dynamic_system},
        ]

        initial_prompt = f"Goal: Explore {target_url} and synthesize standalone crawler to extract: {goal}."
        messages.append({"role": "user", "content": initial_prompt})

        for step in range(1, self.max_steps + 1):
            if state.completed:
                break

            self.emit("step_start", {"step": step})

            # Budget redline hint push
            if step >= self.max_steps - 4:
                state.add_correction_hint(
                    f"Redline Alert: Step {step}/{self.max_steps}. Cease exploration. "
                    "Synthesize your crawler immediately and verify with execute_crawler_sandbox."
                )

            round_ctx = build_round_context(state, step, self.max_steps)
            messages.append({"role": "user", "content": round_ctx})

            # Call LLM
            response = self.llm_client.chat_completion(messages, tools=TOOLS_SCHEMA)
            msg = response.choices[0].message
            content = msg.content or ""
            tool_calls = msg.tool_calls or []

            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            if content:
                self.emit("agent_thought", {"thought": content[:300]})

            # Check for completion marker
            if "FINAL:" in content and state.verification_passed:
                state.completed = True
                state.complete_reason = content
                self.emit("completed", {"reason": content})
                break
            elif "FINAL:" in content and not state.verification_passed:
                state.add_correction_hint("Gate Rejection: You declared FINAL but execute_crawler_sandbox has not passed yet. Verify first!")

            # Execute tool calls
            for tc in tool_calls:
                func_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}

                self.emit("tool_call", {"tool": func_name, "args": args})
                pre_block = self.correction_layer.check_pre_tool(state, func_name, args)
                if pre_block:
                    result = pre_block
                else:
                    try:
                        result = await self.tool_manager.execute_tool(state, func_name, args)
                    except Exception as e:
                        result = f"Error executing tool '{func_name}': {str(e)[:300]}"
                        state.add_correction_hint(result)
                self.correction_layer.check_post_tool(state, func_name, result)
                state.record_evidence(func_name, args, result[:300], result)

                self.emit("tool_result", {"tool": func_name, "summary": result[:200]})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result[:2000]
                })

        return state
