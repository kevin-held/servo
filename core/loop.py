import json
import re
import time
import traceback
from PySide6.QtCore import QThread, Signal
from core.sentinel_logger import get_logger


class LoopStep:
    PERCEIVE       = "PERCEIVE"
    CONTEXTUALIZE  = "CONTEXTUALIZE"
    REASON         = "REASON"
    ACT            = "ACT"
    INTEGRATE      = "INTEGRATE"
    IDLE           = "IDLE"


class CoreLoop(QThread):
    """
    The core loop. Six steps. Runs continuously.
    Everything else is data this loop operates on.

        1. PERCEIVE       — what is happening right now?
        2. CONTEXTUALIZE  — what do I know that's relevant?
        3. REASON         — what should happen next?
        4. ACT            — do the thing
        5. INTEGRATE      — what changed? what did I learn?
        6. GOTO 1
    """

    step_changed    = Signal(str)        # current step name
    trace_event     = Signal(str, str)   # step, message
    response_ready  = Signal(str, str)   # final response text, tool_used (for role identity)
    tool_called     = Signal(str, str, str)  # tool_name, args_json, result
    error_occurred  = Signal(str)
    stream_chunk    = Signal(str)        # streamed textual chunk
    stream_started  = Signal()
    stream_finished = Signal()
    context_limit_changed = Signal(int)
    goals_changed         = Signal(object)
    log_event             = Signal(str, str, str, str)  # level, component, message, context_json

    def __init__(self, state, ollama, tools):
        super().__init__()
        self.state  = state
        self.ollama = ollama
        self.tools  = tools
        self._running       = False
        self._pending_input = None
        self.stream_enabled = False
        self.continuous_mode = False
        self._goal_achieved = False
        self.context_limit  = 15
        self.default_context_limit = 15
        self._stable_loop_count = 0
        self.verbosity      = "Normal"
        self.loop_limit     = 3
        self._pending_tool_payload = None
        self._sentinel = get_logger()
        self._active_role = ""  # Current role key (e.g. "sentinel") set by goal-due prods

    def submit_input(self, text: str, image_b64: str = ""):
        self._pending_input = {"text": text, "image": image_b64}
        self._active_role = ""  # User input clears role — they're talking to "Assistant"

    def stop(self):
        self._running = False

    # ──────────────────────────────────────────────
    # Main thread
    # ──────────────────────────────────────────────

    def run(self):
        """
        The sole orchestrator of the execution loop.
        _run_cycle() executes ONE cycle and returns a directive; this method
        decides what to do next — guaranteeing _pending_input is always checked
        between every cycle, so the user is never locked out.
        """
        self._running  = True
        self._set_step(LoopStep.IDLE)
        _next_payload      = None   # payload queued for the next cycle
        _loop_index        = 0      # tracks iteration depth for context-limit enforcement
        _last_expiry_check = 0.0    # timestamp of last idle expiry sweep

        self._slog("INFO", "core_loop", "Core loop started", {
            "model": self.ollama.model,
            "continuous_mode": self.continuous_mode,
        })

        while self._running:
            # User input always interrupts continuous re-loops — highest priority.
            if self._pending_input is not None:
                _next_payload       = self._pending_input
                self._pending_input = None
                _loop_index         = 0

            if _next_payload is not None:
                directive     = self._run_cycle(_next_payload, loop_index=_loop_index)
                _next_payload = None
                action        = directive.get("action", "done")

                if action == "chain":
                    # Enforce loop_limit when not in continuous mode
                    if not self.continuous_mode and _loop_index >= self.loop_limit - 1:
                        self._trace(LoopStep.IDLE, "Loop limit reached. Pausing for user review.")
                        _loop_index = 0
                        self._set_step(LoopStep.IDLE)
                    else:
                        _next_payload = directive["payload"]
                        _loop_index  += 1

                elif action == "continue" and self.continuous_mode:
                    _next_payload = directive["payload"]
                    _loop_index  += 1

                elif action == "tool_confirm" and self.continuous_mode:
                    # Grace cycle: model just used a tool but didn't chain. Give it one
                    # free cycle to decide whether to chain more work before we prod for goals.
                    _next_payload = directive["payload"]
                    _loop_index  += 1

                elif action == "snooze" and self.continuous_mode:
                    snooze_s   = directive.get("snooze_seconds", 60)
                    snooze_min = max(1, int(snooze_s / 60))
                    self.response_ready.emit(
                        f"[Continuous Mode] All goals are snoozing. "
                        f"Next check in ~{snooze_min} minute(s). "
                        f"You can send a message at any time.",
                        "manager"
                    )
                    self._set_step(LoopStep.IDLE)
                    # Sleep in 1-second ticks so user input can interrupt immediately
                    elapsed = 0
                    while self._running and self.continuous_mode and elapsed < snooze_s:
                        if self._pending_input is not None:
                            break   # user typed — handled at top of while loop
                        time.sleep(1)
                        elapsed += 1
                    # Only re-queue the prod if still running, still continuous, no new user input
                    if self._running and self.continuous_mode and self._pending_input is None:
                        _next_payload = directive["payload"]
                        _loop_index  += 1

                else:  # "done" or unknown
                    _loop_index = 0
                    self._set_step(LoopStep.IDLE)
            else:
                # Idle path: check every 30 seconds for expired finite goals so they
                # auto-retire even when no cycles are running.
                now = time.time()
                if now - _last_expiry_check >= 30.0:
                    self._check_goals_status()
                    _last_expiry_check = now
                time.sleep(0.05)

    def _run_cycle(self, user_payload: dict, loop_index: int = 0) -> dict:
        """
        Execute ONE cycle: PERCEIVE → CONTEXTUALIZE → REASON → ACT → INTEGRATE.
        Returns a directive dict consumed by run():
            {"action": "done"}                                   — stop, go idle
            {"action": "chain",    "payload": {...}}             — re-loop immediately (tool chain)
            {"action": "continue", "payload": {...}}             — continuous mode re-loop
            {"action": "snooze",   "payload": {...},
             "snooze_seconds": N}                                — continuous mode, all goals sleeping
        """
        try:
            current_text  = user_payload.get("text", "")
            current_image = user_payload.get("image", "")
            # _pending_tool carries a pre-parsed tool call for chained execution
            pending_tool  = user_payload.get("_pending_tool")
            raw_prev_resp = user_payload.get("_raw_response", "")

            if loop_index > 0:
                self._trace(LoopStep.PERCEIVE, f"--- CYCLE {loop_index + 1} {'(Continuous)' if self.continuous_mode else f'/ {self.loop_limit}'} ---")

            # Intercept user-pasted manual tool calls on the very first cycle
            if loop_index == 0 and not pending_tool:
                pasted_call = self._parse_tool_call(current_text)
                if pasted_call:
                    self._trace(LoopStep.PERCEIVE, "Intercepted user-pasted tool call! Bypassing reasoning.")
                    pending_tool  = pasted_call
                    raw_prev_resp = current_text
                    current_text  = ""

            # ── PERCEIVE ──────────────────────────────────
            if pending_tool:
                perceived = {"raw_input": current_text, "image": current_image,
                             "timestamp": time.time(), "type": "system"}
                self._set_step(LoopStep.PERCEIVE)
                self._trace(LoopStep.PERCEIVE, "Auto-chaining payload intercepted")
            else:
                perceived = self._perceive(current_text, current_image)

            # ── CONTEXTUALIZE ──────────────────────────────
            context = self._contextualize(perceived)

            # ── REASON ─────────────────────────────────────
            if pending_tool:
                reasoning = {"raw_response": raw_prev_resp, "tool_call": pending_tool, "context": context}
                self._set_step(LoopStep.REASON)
                self._trace(LoopStep.REASON, f"Skipped model query — pushing auto-chained tool: {pending_tool.get('tool')}")
            else:
                # Hardware self-healing
                from .hardware import get_resource_status
                hw_status = get_resource_status()
                if hw_status["status"] == "Critical":
                    self._slog("CRITICAL", "hardware", "Hardware critical — throttling", {
                        "ram_percent": hw_status["ram_percent"],
                        "vram_percent": hw_status["vram_percent"],
                    })
                    self._trace(LoopStep.REASON,
                        f"Hardware Critical (RAM: {hw_status['ram_percent']}%, "
                        f"VRAM: {hw_status['vram_percent']}%). Purging KV cache & throttling context.")
                    if hasattr(self.ollama, "clear_kv_cache"):
                        self.ollama.clear_kv_cache()
                    self.context_limit = max(5, self.context_limit - 2)
                    self.context_limit_changed.emit(self.context_limit)
                    self._stable_loop_count = 0
                    time.sleep(3)
                else:
                    self._stable_loop_count += 1
                    if self._stable_loop_count >= 5 and self.context_limit < self.default_context_limit:
                        self.context_limit = self.default_context_limit
                        self.context_limit_changed.emit(self.context_limit)
                        self._stable_loop_count = 0
                        self._trace(LoopStep.REASON, "Hardware usage stabilized. Restoring normal context limits.")
                reasoning = self._reason(context, current_loop=loop_index)

            # ── ACT ────────────────────────────────────────
            result = self._act(reasoning, current_loop=loop_index)

            # ── INTEGRATE ──────────────────────────────────
            self._integrate(current_text, current_image, result, is_chained=(loop_index > 0))

            # Refresh goal GUI tracker on any goal_manager call
            if result.get("tool_used") == "goal_manager":
                try:
                    import os as _os
                    goal_path = _os.path.join(_os.getcwd(), "goals.json")
                    with open(goal_path, "r", encoding="utf-8") as f:
                        self.goals_changed.emit(json.load(f))
                except Exception:
                    pass
                if "SUCCESS: Goal" in str(result.get("tool_result", "")):
                    self._trace(LoopStep.INTEGRATE, "Finite Goal officially completed!")

            response_text = result["response"]

            # ── DETERMINE NEXT ACTION ──────────────────────
            chained_call = self._parse_tool_call(response_text)

            if chained_call and (self.continuous_mode or loop_index < self.loop_limit - 1):
                # Always surface model text before chaining (fixes empty-output bug)
                if response_text.strip():
                    self.response_ready.emit(response_text, self._active_role)
                self._trace(LoopStep.INTEGRATE, "Model chained a tool block! Re-looping automatically.")
                return {
                    "action": "chain",
                    "payload": {
                        "text":          "",
                        "image":         "",
                        "_pending_tool":  chained_call,
                        "_raw_response": response_text,
                    },
                }

            elif self.continuous_mode:
                self.response_ready.emit(response_text, self._active_role)

                # Issue 1 fix: if a tool was just used and no chain was detected,
                # give the model one 'grace cycle' to decide whether to do more
                # work before we fire a goal-due auto-prod.
                tool_just_used   = result.get("tool_used") is not None
                coming_from_grace = user_payload.get("_grace_cycle", False)

                if tool_just_used and not coming_from_grace:
                    self._trace(LoopStep.INTEGRATE, "Tool completed. Giving model a grace cycle before goal check.")
                    return {
                        "action": "tool_confirm",
                        "payload": {
                            "text": (
                                "SYSTEM: You just completed a tool action. "
                                "If you have additional work to do, invoke another tool now. "
                                "If you are fully done with this task step, reply with plain text only."
                            ),
                            "image": "",
                            "_grace_cycle": True,
                        },
                    }
                has_goals, has_due, snooze_s, due_role = self._check_goals_status()

                if not has_goals:
                    self._trace(LoopStep.IDLE, "Target Queue empty. Halting continuous cycle.")
                    return {"action": "done"}

                if has_due:
                    # Set active role from the due goal
                    if due_role:
                        self._active_role = due_role
                    self._trace(LoopStep.INTEGRATE, f"Due goal detected (role: {due_role or 'none'}). Auto-prodding model.")
                    return {
                        "action": "continue",
                        "payload": {
                            "text": (
                                "SYSTEM (Autonomous Loop): A goal is due. "
                                "Please take necessary actions, and if a continuous goal "
                                "is satisfied for now, use the 'mark_run' action to snooze it."
                            ),
                            "image": "",
                        },
                    }

                snooze_min = max(1, int(snooze_s / 60))
                self._trace(LoopStep.IDLE, f"All goals snoozing. Next due in ~{snooze_min} minute(s).")
                return {
                    "action": "snooze",
                    "payload": {
                        "text": (
                            "SYSTEM (Autonomous Loop): A goal is due. "
                            "Please take necessary actions, and if a continuous goal "
                            "is satisfied for now, use the 'mark_run' action to snooze it."
                        ),
                        "image": "",
                    },
                    "snooze_seconds": snooze_s,
                }

            else:
                self.response_ready.emit(response_text, self._active_role)
                return {"action": "done"}

        except Exception as e:
            self._slog("ERROR", "core_loop", f"Cycle exception: {e}", {
                "traceback": traceback.format_exc(),
                "loop_index": loop_index,
            })
            self.error_occurred.emit(str(e))
            self._set_step(LoopStep.IDLE)
            return {"action": "done"}

    # ──────────────────────────────────────────────
    # Step 1 — PERCEIVE
    # ──────────────────────────────────────────────

    def _perceive(self, text: str, image: str) -> dict:
        self._set_step(LoopStep.PERCEIVE)
        self._trace(LoopStep.PERCEIVE, f"Input received ({len(text)} chars)")
        if image:
            self._trace(LoopStep.PERCEIVE, "Image attachment detected and encoded")
        return {
            "raw_input": text,
            "image":     image,
            "timestamp": time.time(),
            "type":      "user_message",
        }

    # ──────────────────────────────────────────────
    # Step 2 — CONTEXTUALIZE
    # ──────────────────────────────────────────────

    def _contextualize(self, perceived: dict) -> dict:
        self._set_step(LoopStep.CONTEXTUALIZE)

        history = self.state.get_conversation_history(limit=self.context_limit)
        self._trace(LoopStep.CONTEXTUALIZE, f"Loaded {len(history)} conversation turns")

        query = perceived.get("raw_input", "")
        if query:
            memory = self.state.get_relevant_memory(query, limit=5)
            self._trace(LoopStep.CONTEXTUALIZE, f"Loaded {len(memory)} relevant memory entries via vector search")
        else:
            memory = self.state.get_recent_memory(limit=5)
            self._trace(LoopStep.CONTEXTUALIZE, f"Loaded {len(memory)} recent memory entries")

        available_tools = self.tools.get_tool_descriptions()
        enabled = [t["name"] for t in available_tools if t.get("enabled")]
        self._trace(LoopStep.CONTEXTUALIZE, f"Available tools: {enabled}")

        return {
            "input":   perceived["raw_input"],
            "image":   perceived.get("image", ""),
            "history": history,
            "memory":  memory,
            "tools":   available_tools,
        }

    # ──────────────────────────────────────────────
    # Step 3 — REASON
    # ──────────────────────────────────────────────

    # Max times the loop will auto-continue a response truncated by num_predict
    MAX_AUTO_CONTINUES = 2

    def _reason(self, context: dict, current_loop: int = 0) -> dict:
        self._set_step(LoopStep.REASON)

        system_prompt = self._build_system_prompt(context, current_loop=current_loop)
        messages      = self._build_messages(context)

        self._trace(LoopStep.REASON, f"Model: {self.ollama.model}")
        self._trace(LoopStep.REASON, f"Messages: {len(messages)} | Tools: {len(context['tools'])}")

        raw, truncated = self._call_model(system_prompt, messages)

        # Auto-continue if the response was truncated by num_predict
        raw = self._auto_continue(raw, truncated, system_prompt, messages)

        self._trace(LoopStep.REASON, f"Response received ({len(raw)} chars)")

        tool_call = self._parse_tool_call(raw)
        if tool_call:
            self._trace(LoopStep.REASON, f"Tool call detected: {tool_call.get('tool')}")
        else:
            self._trace(LoopStep.REASON, "No tool call — direct response")

        return {
            "raw_response": raw,
            "tool_call":    tool_call,
            "context":      context,
        }

    # ──────────────────────────────────────────────
    # Step 4 — ACT
    # ──────────────────────────────────────────────

    def _act(self, reasoning: dict, current_loop: int = 0) -> dict:
        self._set_step(LoopStep.ACT)
        tool_call = reasoning.get("tool_call")

        if tool_call:
            name   = tool_call.get("tool", "")
            args   = tool_call.get("args", {})

            self._trace(LoopStep.ACT, f"Executing: {name}")
            self._trace(LoopStep.ACT, f"Args: {json.dumps(args)[:200]}")

            self._slog("INFO", "tool_exec", f"Executing tool: {name}", {
                "tool": name,
                "args_preview": json.dumps(args)[:300],
            })

            result = self.tools.execute(name, args)

            # Log tool errors at ERROR level
            result_str = str(result)
            if result_str.startswith("Error"):
                self._slog("ERROR", "tool_exec", f"Tool '{name}' returned error", {
                    "tool": name, "error": result_str[:500],
                })
            else:
                self._slog("DEBUG", "tool_exec", f"Tool '{name}' completed", {
                    "tool": name, "result_preview": result_str[:200],
                })

            self._trace(LoopStep.ACT, f"Result: {result_str[:200]}")
            self.tool_called.emit(name, json.dumps(args), result_str)

            # Feed result back to model for a final response
            followup_messages = (
                self._build_messages(reasoning["context"])
                + [{"role": "assistant", "content": reasoning["raw_response"]}]
                + [{"role": "user",      "content": f"Tool result:\n{result}"}]
            )
            self._trace(LoopStep.ACT, "Sending tool result back to model")
            followup_prompt = self._build_system_prompt(reasoning["context"], is_followup=True, current_loop=current_loop)
            followup, truncated = self._call_model(followup_prompt, followup_messages)

            # Auto-continue if the followup was truncated
            followup = self._auto_continue(followup, truncated, followup_prompt, followup_messages)

            return {"raw_response": reasoning["raw_response"], "response": followup, "tool_used": name, "tool_result": result}

        else:
            self._trace(LoopStep.ACT, "Returning direct response")
            return {"raw_response": reasoning["raw_response"], "response": reasoning["raw_response"], "tool_used": None}

    # ──────────────────────────────────────────────
    # Step 5 — INTEGRATE
    # ──────────────────────────────────────────────

    def _integrate(self, user_input: str, user_image: str, result: dict, is_chained: bool = False):
        self._set_step(LoopStep.INTEGRATE)

        if (user_input or user_image) and not is_chained:
            self.state.add_conversation_turn("user", user_input, user_image)

        if result.get("tool_used"):
            # Avoid duplicate assistant messages during a chain
            if not is_chained:
                self.state.add_conversation_turn("assistant", result["raw_response"])
                
            self.state.add_conversation_turn("user", f"Tool result:\n{result['tool_result']}")
            self.state.add_conversation_turn("assistant", result["response"])
            
            summary = f"Used {result['tool_used']} → {str(result['tool_result'])[:1000]}"
            self.state.add_memory(summary)
            self._trace(LoopStep.INTEGRATE, f"Memory updated: {summary}")
        else:
            self.state.add_conversation_turn("assistant", result["response"])
            self._trace(LoopStep.INTEGRATE, "No tool used — no memory update")

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _check_goals_status(self) -> tuple:
        """
        Read goals.json and return:
            (has_goals: bool, has_due_goals: bool, min_snooze_seconds: float, due_role: str)
        min_snooze_seconds is the time until the soonest continuous goal becomes due.
        due_role is the role key (e.g. 'sentinel') if a role_* goal is due, else ''.
        Also auto-expires any finite goals whose expires_at has elapsed.
        """
        import os as _os
        try:
            goal_path = _os.path.join(_os.getcwd(), "goals.json")
            if not _os.path.exists(goal_path):
                return False, False, 0.0, ""
            with open(goal_path, "r", encoding="utf-8") as f:
                goals_data = json.load(f)
            if not goals_data:
                return False, False, 0.0, ""

            # Auto-expire finite goals whose duration has elapsed
            expired = [
                k for k, v in goals_data.items()
                if v.get("type") == "finite" and v.get("expires_at") and time.time() >= v["expires_at"]
            ]
            if expired:
                for k in expired:
                    del goals_data[k]
                    self._trace(LoopStep.INTEGRATE, f"Finite goal '{k}' auto-expired after duration limit.")
                with open(goal_path, "w", encoding="utf-8") as f:
                    json.dump(goals_data, f, indent=4)
                self.goals_changed.emit(goals_data)
            if not goals_data:
                return False, False, 0.0, ""

            has_due    = False
            due_role   = ""
            min_snooze = float("inf")
            for k, v in goals_data.items():
                if v.get("type") == "finite":
                    has_due = True
                elif v.get("type") == "continuous":
                    last    = v.get("last_run", 0)
                    sched_s = v.get("schedule_minutes", 60) * 60
                    remaining = sched_s - (time.time() - last)
                    if remaining <= 0:
                        has_due = True
                        # Extract role key from goal name (e.g. 'role_sentinel' → 'sentinel')
                        if k.startswith("role_") and not due_role:
                            due_role = k[5:]  # strip 'role_' prefix
                    else:
                        min_snooze = min(min_snooze, remaining)

            snooze_s = min_snooze if min_snooze != float("inf") else 60.0
            return True, has_due, snooze_s, due_role
        except Exception:
            return False, False, 0.0, ""

    def _call_model(self, system_prompt: str, messages: list) -> tuple:
        """
        Unified model call that handles both streaming and non-streaming modes.

        Returns:
            tuple: (content: str, truncated: bool)
        """
        if self.stream_enabled:
            self.stream_started.emit()
            raw = ""
            truncated = False
            for chunk in self.ollama.chat_stream(system_prompt, messages):
                # The final yielded item is a sentinel dict with truncation info
                if isinstance(chunk, dict) and chunk.get("done"):
                    truncated = chunk.get("truncated", False)
                else:
                    raw += chunk
                    self.stream_chunk.emit(chunk)
            self.stream_finished.emit()
            return raw, truncated
        else:
            return self.ollama.chat(system_prompt, messages)

    def _auto_continue(self, text: str, truncated: bool, system_prompt: str, messages: list) -> str:
        """
        If the model's response was truncated by num_predict, automatically
        send a 'Continue' follow-up and concatenate the result. Up to
        MAX_AUTO_CONTINUES attempts to avoid infinite loops.
        """
        for i in range(self.MAX_AUTO_CONTINUES):
            if not truncated:
                break

            self._slog("WARNING", "core_loop", f"Response truncated by num_predict — auto-continuing ({i + 1}/{self.MAX_AUTO_CONTINUES})", {
                "chars_so_far": len(text),
            })
            self._trace(LoopStep.REASON, f"Response truncated — auto-continuing ({i + 1}/{self.MAX_AUTO_CONTINUES})")

            # Build continuation request
            continuation_messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "Your previous response was cut off. Continue exactly where you left off."},
            ]

            continuation, truncated = self._call_model(system_prompt, continuation_messages)
            text += continuation

        return text

    def _set_step(self, step: str):
        self.step_changed.emit(step)

    def _trace(self, step: str, message: str):
        self.trace_event.emit(step, message)
        self.state.add_trace(step, message)

    def _slog(self, level: str, component: str, message: str, context: dict = None):
        """Emit a structured log entry and notify the GUI."""
        self._sentinel.log(level, component, message, context)
        self.log_event.emit(level, component, message, json.dumps(context or {}))

    def _get_health_summary(self) -> str:
        """
        Build a concise health status string for the system prompt.
        Only includes actionable information — stays empty when everything is healthy.
        """
        lines = []
        try:
            # Hardware
            from .hardware import get_resource_status
            hw = get_resource_status()
            status = hw.get("status", "OK")
            ram = hw.get("ram_percent", 0)
            vram = hw.get("vram_percent", 0)

            if status == "Critical":
                lines.append(f"⚠ HARDWARE CRITICAL — RAM: {ram}%, VRAM: {vram}%. Consider reducing context_limit via system_config tool.")
            elif status == "Warning" or ram > 80 or vram > 80:
                lines.append(f"Hardware: RAM {ram}%, VRAM {vram}% (elevated)")
            else:
                lines.append(f"Hardware: OK (RAM {ram}%, VRAM {vram}%)")

            # Recent errors from Sentinel
            error_count = 0
            try:
                counts = self._sentinel.get_error_counts(minutes=60, bucket_minutes=60)
                error_count = sum(d["count"] for d in counts)
            except Exception:
                pass

            if error_count > 5:
                lines.append(f"⚠ {error_count} errors in the last hour. Use log_query tool to investigate.")
            elif error_count > 0:
                lines.append(f"Errors (last hour): {error_count}")

        except Exception:
            pass

        return "\n".join(lines)

    def _build_system_prompt(self, context: dict, is_followup: bool = False, current_loop: int = 0) -> str:
        import os
        
        tool_lines = ""
        for t in context.get("tools", []):
            if t.get("enabled", True):
                tool_lines += f"\n  {t['name']}: {t['description']}"
                tool_lines += f"\n    Schema: {json.dumps(t['schema'])}"

        memory_lines = ""
        for m in context.get("memory", []):
            memory_lines += f"\n  - {m['content']}"

        working_memory = self.state.get("working_memory", "")

        model_safe_name = self.ollama.model.replace(":", "_").replace(".", "_")
        notes_folder = os.path.join(os.getcwd(), f"{model_safe_name}_notes")

        goals_text = ""
        try:
            goal_path = os.path.join(os.getcwd(), "goals.json")
            if os.path.exists(goal_path):
                with open(goal_path, "r", encoding="utf-8") as f:
                    gls = json.load(f)
                    if gls:
                        goals_text += "\n\n[ACTIVE GOALS]"
                        goals_text += "\nCRITICAL: You must execute FINITE goals (Priority 1) completely using tools before actively working on CONTINUOUS routines (Priority 2)."
                        for k, v in gls.items():
                            if v.get("type") == "finite":
                                expires_at = v.get("expires_at")
                                if expires_at:
                                    mins_left = max(0, int((expires_at - time.time()) / 60))
                                    goals_text += f"\n  - [FINITE PRIORITY 1] {k}: {v.get('description')} (Auto-expires in {mins_left} min)"
                                else:
                                    goals_text += f"\n  - [FINITE PRIORITY 1] {k}: {v.get('description')}"
                        for k, v in gls.items():
                            if v.get("type") == "continuous":
                                last_run = v.get("last_run", 0)
                                sched_sec = v.get("schedule_minutes", 60) * 60
                                time_since = time.time() - last_run
                                if time_since >= sched_sec:
                                    goals_text += f"\n  - [CONTINUOUS PRIORITY 2] {k}: {v.get('description')} (DUE NOW - Please execute and call goal_manager mark_run)"
                                else:
                                    snooze_min = int((sched_sec - time_since) / 60)
                                    goals_text += f"\n  - [CONTINUOUS PRIORITY 2] {k}: {v.get('description')} (Snoozing for {snooze_min} more minutes)"
        except Exception:
            pass

        base = f"""You are an intelligent local AI assistant with access to tools and persistent memory.

[SYSTEM ENVIRONMENT]
Model Identity: {self.ollama.model}
Temperature: {self.ollama.temperature}
Max Tokens: {self.ollama.num_predict}
Context Limit: {self.context_limit} turns

[WORKING MEMORY]
{working_memory if working_memory else "Empty. Use memory_manager tool to document persistent goals or project logic."}

[WORKSPACE POLICY]
For security, your filesystem access (both READ and WRITE) is strictly sandboxed to the local project workspace.
Furthermore, you MUST strictly confine all your newly generated files and autonomous WRITE operations to your dedicated notes folder:
-> {notes_folder}
If this folder does not exist yet, you are authorized to create it using your tools. Do not write outside this folder.
{goals_text}

AVAILABLE TOOLS:{tool_lines if tool_lines else " None enabled."}

To use a tool, you MUST respond with exactly ONE JSON block in this exact format:
```json
{{"tool": "tool_name", "args": {{"param": "value"}}}}
```

IMPORTANT RULES:
1. You may only invoke ONE tool per response. Do not use multiple tools at the same time.
2. If your task requires multiple tools, use the first tool. The system will automatically execute it and return the result to you in a loop. You may then immediately invoke another tool in your follow-up response.
3. ALWAYS strictly use forward slashes `/` for all file paths, even on Windows, to prevent JSON escaping errors.
4. YOU are the autonomous agent. DO NOT ask the user to manually run tools or commands. YOU must execute tools yourself by outputting the JSON block!
5. If using a reasoning model, you may provide your reasoning inside <think> tags before your response.
6. If no further tools are needed, respond normally in plain text summarizing your actions.
7. LARGE FILES: Tool outputs exceeding ~8000 chars are automatically truncated. For large files, use filesystem read with `max_lines` to read in windows. Use `append` to build files incrementally instead of one large write.
8. SCREENSHOTS: Images are auto-scaled to 1024x1024 before being sent to you. To inspect fine details, take a full screenshot first, then use the `region` parameter (e.g. '0,0,960,540' for top-left quadrant) to zoom into the relevant area."""

        # ── System Health Preamble (passive awareness) ──
        health_lines = self._get_health_summary()
        if health_lines:
            base += f"\n\n[SYSTEM HEALTH]\n{health_lines}"

        base += f"\n\n[SYSTEM STATUS] You are currently on tool-iteration {current_loop + 1}."
        
        if not self.continuous_mode:
            base += f" Maximum allowed limits: {self.loop_limit}."
        else:
            base += f" Continuous Mode is ACTIVE. Keep chaining tools endlessly to loop until all finite goals are cleared."
        
        # If the model is generating followup during the final allowed loop limit, physically constrain its behaviour
        if is_followup and (current_loop + 1 >= self.loop_limit) and not self.continuous_mode:
            base += "\n[SYSTEM STATUS] Note: The autonomous limit has been reached. If you output a tool request now, it will not execute automatically. It will pause for user review."

        if is_followup:
            if self.verbosity == "Concise":
                base += "\n5. Provide a very concise, direct 1-sentence summary of your actions."
            elif self.verbosity == "Detailed":
                base += "\n5. Exhaustively explain your logic and findings step-by-step."
                
        base += f"\n\nMEMORY:{memory_lines if memory_lines else ' Empty.'}"
        return base

    def _build_messages(self, context: dict) -> list:
        messages = []
        for t in context.get("history", []):
            msg = {"role": t["role"], "content": t["content"]}
            if t.get("image"):
                msg["images"] = [t["image"]]
            messages.append(msg)
            
        user_msg = {"role": "user", "content": context["input"]}
        if context.get("image"):
            user_msg["images"] = [context["image"]]
        messages.append(user_msg)
        return messages

    def _parse_tool_call(self, text: str) -> dict | None:
        # Strip <think>...</think> block if present
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        
        # Try to find a JSON block specifically
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Fallback: find the first '{' and the last '}'
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and start < end:
                json_str = text[start:end+1]
            else:
                json_str = text
                
        def _try_parse(s: str) -> dict | None:
            try:
                p = json.loads(s)
                if isinstance(p, dict) and "tool" in p: return p
            except Exception:
                return None
                
        # 1. Attempt direct parse
        parsed = _try_parse(json_str)
        if parsed: return parsed
        
        # 2. Attempt trailing bracket trimming (handles hallucinations like "}}}")
        temp_str = json_str
        for _ in range(5):
            if temp_str.endswith("}"):
                temp_str = temp_str[:-1]
                parsed = _try_parse(temp_str + "}")
                if parsed: return parsed

        # 3. Fallback: frequently models output unescaped Windows paths like C:\Users
        fixed_str = re.sub(r'\\(?![\"\\/bfnrtu])', r'\\\\', json_str)
        parsed = _try_parse(fixed_str)
        if parsed: return parsed
        
        # 4. Fallback: multiline unescaped strings
        fixed_str = fixed_str.replace('\n', '\\n').replace('\r', '\\r')
        parsed = _try_parse(fixed_str)
        if parsed: return parsed
            
        return None
