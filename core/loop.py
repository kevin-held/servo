import json
import re
import threading
import time
import traceback
from PySide6.QtCore import QThread, Signal
from core.sentinel_logger import get_logger
from core.ollama_client import ChatCancelled


class LoopStep:
    PERCEIVE       = "PERCEIVE"
    CONTEXTUALIZE  = "CONTEXTUALIZE"
    REASON         = "REASON"
    ACT            = "ACT"
    INTEGRATE      = "INTEGRATE"
    OBSERVE        = "OBSERVE"   # formerly IDLE — passive watch for external triggers


class CoreLoop(QThread):
    """
    The core loop. Six steps. Runs continuously.
    Everything else is data this loop operates on.

        1. PERCEIVE       — what is happening right now?
        2. CONTEXTUALIZE  — what do I know that's relevant?
        3. REASON         — what should happen next?
        4. ACT            — do the thing
        5. INTEGRATE      — what changed? what did I learn?
        6. OBSERVE        — watch for external triggers (goals, user input, file changes)
                            while doing minimal work, then GOTO 1.
    """

    step_changed    = Signal(str)        # current step name
    trace_event     = Signal(str, str)   # step, message
    response_ready  = Signal(str, str)   # final response text, tool_used (for role identity)
    tool_called     = Signal(str, str, str)  # tool_name, args_json, result
    error_occurred  = Signal(str)
    stream_chunk    = Signal(str)        # streamed textual chunk
    stream_started  = Signal()
    stream_finished = Signal()
    conversation_history_changed = Signal(int)
    goals_changed                = Signal(object)
    log_event                    = Signal(str, str, str, str)  # level, component, message, context_json
    active_role_changed          = Signal(str)  # role_key ("" means servo default)

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
        self.conversation_history         = 15
        self.default_conversation_history = 15
        self._stable_loop_count = 0
        self.verbosity      = "Normal"
        # chain_limit:            max chained tool calls within one user turn.
        # autonomous_loop_limit:  max continuous-mode re-loops before forced pause
        #                        (0 = unbounded — continuous mode runs until goals
        #                         clear or the user interrupts).
        self.chain_limit             = 3
        self.autonomous_loop_limit   = 0
        self._autonomous_cycle_count = 0
        self._pending_tool_payload = None
        self._sentinel = get_logger()
        self._active_role = ""  # Current role key (e.g. "sentinel") set by goal-due prods

        # Cancellation — set by submit_input to interrupt an in-flight model call.
        # Cleared at the top of every cycle so each fresh cycle starts non-cancelled.
        self._cancel_event = threading.Event()

        # Grace-cycle cap — consecutive tool_confirm cycles without real progress.
        # Resets on real user input or when the model chains into actual work.
        self._grace_cycle_count        = 0
        self.max_consecutive_grace     = 2

        # Truncation handling (promoted from class constant so it's configurable at runtime)
        self.max_auto_continues = 2

        # Telemetry counters — surfaced via context_dump
        self.truncations_total           = 0
        self.auto_continues_total        = 0
        self.auto_continue_give_ups_total = 0
        self.followup_truncations_total  = 0
        self.hardware_throttle_total     = 0
        self.user_interrupts_total       = 0
        # Phase 2 (D-20260419-01): count successful INTEGRATE-time
        # conversation history compressions. Incremented only when a
        # summary is actually persisted; empty-response / exception
        # paths do NOT advance this counter.
        self.history_compressions_total  = 0

        # Cached manifest (loaded lazily, re-read on each build for hot-edits)
        self._manifest_cache     = None
        self._manifest_mtime     = 0

        # Cached role metadata (priorities) — re-read when roles.json mtime changes
        self._roles_cache        = None
        self._roles_mtime        = 0

        # Cached persona core (codex/persona_core.md) — re-read when file mtime changes
        self._persona_cache      = None
        self._persona_mtime      = 0

        # Cached role manifests (codex/role_manifests/<role>.md) — one entry per role,
        # each tracked by mtime so hot-edits are picked up without restart. Only the
        # currently active role's manifest is injected into the prompt, so these
        # caches stay small even if every role ever gets a manifest file.
        self._role_manifest_cache: dict[str, str]   = {}
        self._role_manifest_mtime: dict[str, float] = {}

    def submit_input(self, text: str, image_b64: str = ""):
        self._pending_input = {"text": text, "image": image_b64}
        if self._active_role:
            # User input clears the overlay — they're talking to plain Servo
            self._active_role = ""
            self.active_role_changed.emit("")
        self._grace_cycle_count        = 0   # real user turn → grace counter resets
        self._autonomous_cycle_count   = 0   # and the continuous-mode cycle counter too
        # If a model call is in flight, interrupt it so the user isn't locked out.
        if not self._cancel_event.is_set():
            self._cancel_event.set()
            self.user_interrupts_total += 1

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
        self._set_step(LoopStep.OBSERVE)
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
                    # Enforce chain_limit when not in continuous mode
                    if not self.continuous_mode and _loop_index >= self.chain_limit - 1:
                        self._trace(LoopStep.OBSERVE, "Chain limit reached. Pausing for user review.")
                        _loop_index = 0
                        self._set_step(LoopStep.OBSERVE)
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
                    self._set_step(LoopStep.OBSERVE)
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
                    self._set_step(LoopStep.OBSERVE)
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
        # Fresh cycle — clear any prior cancellation so this run isn't born aborted.
        self._cancel_event.clear()
        is_transient = bool(user_payload.get("_transient", False))
        try:
            current_text  = user_payload.get("text", "")
            current_image = user_payload.get("image", "")
            # _pending_tool carries a pre-parsed tool call for chained execution
            pending_tool  = user_payload.get("_pending_tool")
            raw_prev_resp = user_payload.get("_raw_response", "")

            if loop_index > 0:
                self._trace(LoopStep.PERCEIVE, f"--- CYCLE {loop_index + 1} {'(Continuous)' if self.continuous_mode else f'/ {self.chain_limit}'} ---")

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
                        f"VRAM: {hw_status['vram_percent']}%). Purging KV cache & throttling conversation history.")
                    if hasattr(self.ollama, "clear_kv_cache"):
                        self.ollama.clear_kv_cache()
                    # Model-appropriate floor: half of the model's default, not a hardcoded 5.
                    # This lets larger-context models keep more history under throttle.
                    floor = max(1, self.default_conversation_history // 2)
                    self.conversation_history = max(floor, self.conversation_history - 2)
                    self.conversation_history_changed.emit(self.conversation_history)
                    self._stable_loop_count = 0
                    self.hardware_throttle_total += 1
                    time.sleep(3)
                else:
                    self._stable_loop_count += 1
                    if self._stable_loop_count >= 5 and self.conversation_history < self.default_conversation_history:
                        self.conversation_history = self.default_conversation_history
                        self.conversation_history_changed.emit(self.conversation_history)
                        self._stable_loop_count = 0
                        self._trace(LoopStep.REASON, "Hardware usage stabilized. Restoring normal conversation history.")
                reasoning = self._reason(context, current_loop=loop_index)

            # ── ACT ────────────────────────────────────────
            result = self._act(reasoning, current_loop=loop_index)

            # ── INTEGRATE ──────────────────────────────────
            self._integrate(
                current_text, current_image, result,
                is_chained=(loop_index > 0),
                is_transient=is_transient,
            )

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

            if chained_call and (self.continuous_mode or loop_index < self.chain_limit - 1):
                # Always surface model text before chaining (fixes empty-output bug)
                if response_text.strip():
                    self.response_ready.emit(response_text, self._active_role)
                self._trace(LoopStep.INTEGRATE, "Model chained a tool block! Re-looping automatically.")
                # Real work detected — the grace counter resets.
                self._grace_cycle_count = 0
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
                # work before we fire a goal-due auto-prod. Capped to prevent
                # consecutive no-progress cycles from accumulating forever.
                tool_just_used    = result.get("tool_used") is not None
                coming_from_grace = user_payload.get("_grace_cycle", False)

                if tool_just_used and not coming_from_grace and \
                        self._grace_cycle_count < self.max_consecutive_grace:
                    self._grace_cycle_count += 1
                    self._trace(
                        LoopStep.INTEGRATE,
                        f"Tool completed. Grace cycle {self._grace_cycle_count}/{self.max_consecutive_grace} before goal check.",
                    )
                    return {
                        "action": "tool_confirm",
                        "payload": {
                            "text": (
                                "SYSTEM: You just completed a tool action. "
                                "If you have additional work to do, invoke another tool now. "
                                "If you are fully done with this task step, reply with plain text only."
                            ),
                            "image":        "",
                            "_grace_cycle": True,
                            "_transient":   True,   # never persisted to conversation
                        },
                    }

                if coming_from_grace and not tool_just_used:
                    # Grace cycle produced no tool call — force the counter back to 0 so
                    # goal-due nudging can resume, but don't spam another grace cycle.
                    self._grace_cycle_count = 0

                # Autonomous-loop cap — if set, stop after N continuous re-loops so the
                # user can review before the agent runs away. 0 = disabled.
                if self.autonomous_loop_limit > 0 and \
                        self._autonomous_cycle_count >= self.autonomous_loop_limit:
                    self._trace(
                        LoopStep.OBSERVE,
                        f"Autonomous loop limit ({self.autonomous_loop_limit}) reached. Pausing for user review.",
                    )
                    self._autonomous_cycle_count = 0
                    return {"action": "done"}

                has_goals, has_due, snooze_s, due_role, other_due_roles = self._check_goals_status()

                if not has_goals:
                    self._trace(LoopStep.OBSERVE, "Target Queue empty. Halting continuous cycle.")
                    return {"action": "done"}

                if has_due:
                    # Set active role from the due goal
                    if due_role and due_role != self._active_role:
                        self._active_role = due_role
                        self.active_role_changed.emit(due_role)
                    self._autonomous_cycle_count += 1
                    self._trace(LoopStep.INTEGRATE, f"Due goal detected (role: {due_role or 'none'}). Auto-prodding model.")

                    # Preemptive auto-tool: if this role has an auto_tool
                    # configured in roles.json, fire it now so the nudge can
                    # deliver the result alongside the task description. This
                    # collapses the typical "be the role" → "invoke the setup
                    # tool" → "do the actual work" cycle into a single model
                    # round-trip when the setup tool is deterministic.
                    auto_tool_output = self._run_auto_tool_for_role(due_role)
                    roles_live = self._load_roles()
                    nudge_text = self._build_due_role_nudge(
                        due_role, other_due_roles, roles_live, auto_tool_output,
                    )
                    return {
                        "action": "continue",
                        "payload": {
                            "text":       nudge_text,
                            "image":      "",
                            "_transient": True,   # never persisted to conversation
                        },
                    }

                snooze_min = max(1, int(snooze_s / 60))
                self._trace(LoopStep.OBSERVE, f"All goals snoozing. Next due in ~{snooze_min} minute(s).")
                # Snooze path: nothing is actually due right now. We still
                # carry a nudge text in the payload in case the snooze is
                # interrupted, but the auto_tool deliberately does not fire —
                # it should only run when a role is genuinely due, to avoid
                # burning tool calls and log entries on no-op ticks.
                snooze_nudge = self._build_due_role_nudge(
                    due_role, other_due_roles, self._load_roles(), auto_tool_output="",
                )
                return {
                    "action": "snooze",
                    "payload": {
                        "text":       snooze_nudge,
                        "image":      "",
                        "_transient": True,   # never persisted to conversation
                    },
                    "snooze_seconds": snooze_s,
                }

            else:
                self.response_ready.emit(response_text, self._active_role)
                return {"action": "done"}

        except ChatCancelled:
            # User typed while a model call was in flight — discard the partial
            # response, surface a trace, and return done so run() immediately
            # re-enters with the fresh _pending_input.
            self._slog("INFO", "core_loop", "Chat cancelled by user interrupt", {"loop_index": loop_index})
            self._trace(LoopStep.OBSERVE, "Generation interrupted by user input — discarding partial response.")
            self._set_step(LoopStep.OBSERVE)
            return {"action": "done"}
        except Exception as e:
            self._slog("ERROR", "core_loop", f"Cycle exception: {e}", {
                "traceback": traceback.format_exc(),
                "loop_index": loop_index,
            })
            self.error_occurred.emit(str(e))
            self._set_step(LoopStep.OBSERVE)
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

        history = self.state.get_conversation_history(limit=self.conversation_history)
        self._trace(LoopStep.CONTEXTUALIZE, f"Loaded {len(history)} conversation turns")

        # Phase 2 (D-20260419-01): load the latest conversation summary
        # if one exists. It's rendered as a [PRIOR CONTEXT] block in the
        # system prompt and used to filter the Ollama message list so
        # the model doesn't see raw turns it's already remembering via
        # the summary. `None` when no summary has been written yet.
        history_summary = self.state.get_latest_conversation_summary()
        if history_summary:
            self._trace(
                LoopStep.CONTEXTUALIZE,
                f"Loaded conversation summary #{history_summary['id']} "
                f"covering ids {history_summary['covers_from_id']}..{history_summary['covers_to_id']}"
            )

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
            "history_summary": history_summary,
            "memory":  memory,
            "tools":   available_tools,
        }

    # ──────────────────────────────────────────────
    # Step 3 — REASON
    # ──────────────────────────────────────────────

    def _reason(self, context: dict, current_loop: int = 0) -> dict:
        self._set_step(LoopStep.REASON)

        system_prompt = self._build_system_prompt(context, current_loop=current_loop)
        messages      = self._build_messages(context)

        self._trace(LoopStep.REASON, f"Model: {self.ollama.model}")
        self._trace(LoopStep.REASON, f"Messages: {len(messages)} | Tools: {len(context['tools'])}")

        raw, truncated = self._call_model(system_prompt, messages)
        if truncated:
            self.truncations_total += 1

        # Auto-continue if the response was truncated by num_predict
        raw = self._auto_continue(raw, truncated, system_prompt, messages, phase="reason")

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
            if truncated:
                self.followup_truncations_total += 1

            # Auto-continue if the followup was truncated
            followup = self._auto_continue(followup, truncated, followup_prompt, followup_messages, phase="followup")

            return {"raw_response": reasoning["raw_response"], "response": followup, "tool_used": name, "tool_result": result}

        else:
            self._trace(LoopStep.ACT, "Returning direct response")
            return {"raw_response": reasoning["raw_response"], "response": reasoning["raw_response"], "tool_used": None}

    # ──────────────────────────────────────────────
    # Step 5 — INTEGRATE
    # ──────────────────────────────────────────────

    def _integrate(self, user_input: str, user_image: str, result: dict,
                   is_chained: bool = False, is_transient: bool = False):
        """
        Persist the turn. Transient cycles (grace / goal-prod SYSTEM nudges) skip
        conversation persistence so loop-control signals don't pollute history.
        Tool results and followup responses produced *inside* a transient cycle
        are still real work and are persisted.
        """
        self._set_step(LoopStep.INTEGRATE)

        if (user_input or user_image) and not is_chained and not is_transient:
            self.state.add_conversation_turn("user", user_input, user_image)

        if result.get("tool_used"):
            # Avoid duplicate assistant messages during a chain or transient cycle.
            if not is_chained and not is_transient:
                self.state.add_conversation_turn("assistant", result["raw_response"])

            self.state.add_conversation_turn("user", f"Tool result:\n{result['tool_result']}")
            self.state.add_conversation_turn("assistant", result["response"])

            summary = f"Used {result['tool_used']} → {str(result['tool_result'])[:1000]}"
            self.state.add_memory(summary)
            self._trace(LoopStep.INTEGRATE, f"Memory updated: {summary}")
        else:
            if is_transient:
                # Pure ack to a SYSTEM nudge with no tool use — orphan reply,
                # don't persist it or we pollute future CONTEXTUALIZE loads.
                self._trace(LoopStep.INTEGRATE, "Transient cycle, no tool — skipping conversation persistence.")
            else:
                self.state.add_conversation_turn("assistant", result["response"])
                self._trace(LoopStep.INTEGRATE, "No tool used — no memory update")

        # Phase 2 (D-20260419-01): after any real turns have been
        # persisted, ask the history compressor whether it wants to
        # roll up the oldest raw turns into a summary. The predicate
        # is cheap (one COUNT + one SELECT MAX) so running it every
        # INTEGRATE is fine; the actual kernel call only fires when
        # the 2× cap threshold is met.
        #
        # Transient cycles skipped nothing real to persist, so skip
        # compression too — nothing changed.
        if not is_transient:
            try:
                from core.history_compressor import maybe_compress
                report = maybe_compress(self.state, self.conversation_history)
            except Exception as e:
                # Compressor must never crash the loop. Log and move on.
                self._trace(LoopStep.INTEGRATE,
                            f"history_compressor raised {type(e).__name__}: {e}")
                report = None
            if report is not None:
                self.history_compressions_total += 1
                self._trace(
                    LoopStep.INTEGRATE,
                    f"Compressed {report['turns_compressed']} turns into summary "
                    f"#{report['summary_id']} (covers {report['covers_from_id']}.."
                    f"{report['covers_to_id']}, {report['summary_length']} chars, "
                    f"model={report['model_used']})"
                )

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _load_roles(self) -> dict:
        """
        Load roles.json with mtime caching so we don't re-read it every cycle.
        Returns the roles dict (possibly empty) — safe to index with .get().
        """
        import os as _os
        roles_path = _os.path.join(_os.getcwd(), "roles.json")
        if not _os.path.exists(roles_path):
            return {}
        try:
            mtime = _os.path.getmtime(roles_path)
            if self._roles_cache is not None and mtime == self._roles_mtime:
                return self._roles_cache
            with open(roles_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            self._roles_cache = data
            self._roles_mtime = mtime
            return data
        except Exception:
            return self._roles_cache or {}

    def _substitute_auto_tool_args(self, args: dict) -> dict:
        """
        Substitute path placeholders in auto_tool arg values. Keeps manifests
        model-agnostic: a role can reference `{workspace_folder}` in roles.json
        and the loop expands it to the backing model's actual workspace path
        at call time.

        Supported placeholders:
            {workspace_folder}  → `workspace/<model_safe_name>`
            {model_safe_name}   → the sanitized model identifier
            {codex_folder}      → `codex`

        Substitution is string-only and applied recursively to nested dicts /
        lists. Non-string values pass through untouched.
        """
        model_safe_name  = self.ollama.model.replace(":", "_").replace(".", "_")
        workspace_folder = f"workspace/{model_safe_name}"
        mapping = {
            "workspace_folder": workspace_folder,
            "model_safe_name":  model_safe_name,
            "codex_folder":     "codex",
        }

        def _sub(value):
            if isinstance(value, str):
                out = value
                for key, repl in mapping.items():
                    out = out.replace("{" + key + "}", repl)
                return out
            if isinstance(value, dict):
                return {k: _sub(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_sub(v) for v in value]
            return value

        return _sub(args)

    def _run_auto_tool_for_role(self, role_key: str) -> str:
        """
        If the role defines an `auto_tool` in roles.json, invoke it via the
        tool registry and return the (registry-capped) output. Returns "" if
        no auto_tool is defined or the role is unknown.

        Intent: the auto_tool is a preemptive first tool call that gives the
        due role the data it needs before REASON. Example: Scholar gets the
        delta list, Sentinel gets the last 20 ERRORs, Architect gets the
        architecture review in hand. This saves one model round-trip per
        cycle and makes the role's work more deterministic at cycle start.

        Failures are caught and returned as a short diagnostic string rather
        than raised — a broken auto_tool should not block the cycle.
        """
        if not role_key:
            return ""
        roles = self._load_roles()
        role_meta = roles.get(role_key) or {}
        spec = role_meta.get("auto_tool")
        if not spec:
            return ""
        tool_name = (spec.get("name") or "").strip()
        tool_args = spec.get("args") or {}
        if not tool_name:
            return ""
        if not isinstance(tool_args, dict):
            return f"[auto_tool error: args must be an object, got {type(tool_args).__name__}]"
        tool_args = self._substitute_auto_tool_args(tool_args)
        try:
            self._trace(LoopStep.OBSERVE, f"Auto-tool for role '{role_key}': {tool_name}")
            return self.tools.execute(tool_name, tool_args)
        except Exception as e:
            self._slog("WARNING", "core_loop", f"auto_tool failed for role '{role_key}'",
                       {"tool": tool_name, "args": tool_args, "error": str(e)})
            return f"[auto_tool {tool_name} failed: {e}]"

    def _build_due_role_nudge(
        self,
        due_role: str,
        other_due_roles: list,
        roles_live: dict,
        auto_tool_output: str,
    ) -> str:
        """
        Build the user-turn nudge text sent to the model when a role is due.

        Sections, in order:
            [ROLE DUE]         — title + schedule
            [YOUR TASK]        — live task text from roles.json
            [AUTO-TOOL OUTPUT] — pre-fetched data, if the role has an auto_tool
            [OTHER DUE ROLES]  — other role_* goals also due this cycle
            [WRAP-UP]          — explicit mark_done instruction with exact args

        The nudge is transient (not persisted to conversation history) so it
        never clutters future cycles; each due cycle rebuilds it fresh from
        the live roles.json + current auto_tool output.
        """
        if not due_role:
            # Fallback for non-role finite goals — keep the old short text.
            return (
                "SYSTEM (Autonomous Loop): A goal is due. "
                "Please take necessary actions, and if a continuous goal "
                "is satisfied for now, use the 'mark_done' action to snooze it."
            )

        role = roles_live.get(due_role, {}) or {}
        title    = role.get("title", due_role)
        task     = (role.get("task") or "").strip() or "(no task text in roles.json)"
        sched_m  = int(role.get("schedule_minutes", 60) or 60)

        lines = [
            f"SYSTEM (Autonomous Loop)",
            f"[ROLE DUE] {title} — schedule: every {sched_m} min.",
            "",
            "[YOUR TASK]",
            task,
        ]

        if auto_tool_output:
            lines.extend(["", "[AUTO-TOOL OUTPUT]", auto_tool_output])

        if other_due_roles:
            # Show the other due role keys with their titles if available.
            labeled = []
            for rk in other_due_roles:
                t = (roles_live.get(rk) or {}).get("title", rk)
                labeled.append(f"{rk} ({t})")
            lines.extend([
                "",
                "[OTHER DUE ROLES]",
                "Also queued this cycle (lower priority or less overdue): "
                + ", ".join(labeled),
                "You may chain mark_done calls for multiple roles in one cycle if "
                "their work is satisfied together, but only adopt ONE role's voice "
                "per response.",
            ])

        lines.extend([
            "",
            "[WRAP-UP]",
            "When this role's work is satisfied for this cycle, emit this "
            "JSON tool call verbatim — the loop only recognizes tool calls "
            "that match the fenced-JSON shape documented in AVAILABLE TOOLS:",
            "```json",
            f'{{"tool": "goal_manager", "args": {{"action": "mark_done", "goal_name": "role_{due_role}"}}}}',
            "```",
            "That snoozes this role for its full schedule. Prose like "
            '`goal_manager action="mark_done" ...` is NOT parsed as a tool '
            "call — if you describe the action in words instead of emitting "
            "the JSON block, the role stays due and will fire again next "
            "cycle. Always close the loop with the fenced JSON, even if the "
            "only outcome is 'nothing to report this cycle'.",
        ])

        return "\n".join(lines)

    def _check_goals_status(self) -> tuple:
        """
        Read goals.json and return:
            (has_goals: bool,
             has_due_goals: bool,
             min_snooze_seconds: float,
             due_role: str,
             other_due_roles: list[str])
        min_snooze_seconds is the time until the soonest continuous goal becomes due.
        due_role is the role key (e.g. 'sentinel') if a role_* goal is due, else ''.
        other_due_roles contains the remaining due role keys ordered by the same
        priority/overdue tie-break — useful for the nudge so the model knows what
        else is queued and can chain mark_done calls across multiple roles in one
        cycle when appropriate.
        When multiple role goals are simultaneously due, the winner is picked by
        (priority ascending, overdue-seconds descending) so the choice is
        deterministic — same goals.json + same clock always yields the same winner.
        Also auto-expires any finite goals whose expires_at has elapsed.
        """
        import os as _os
        try:
            goal_path = _os.path.join(_os.getcwd(), "goals.json")
            if not _os.path.exists(goal_path):
                return False, False, 0.0, "", []
            with open(goal_path, "r", encoding="utf-8") as f:
                goals_data = json.load(f)
            if not goals_data:
                return False, False, 0.0, "", []

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
                return False, False, 0.0, "", []

            roles      = self._load_roles()
            has_due    = False
            min_snooze = float("inf")
            # Collect all due role goals with their (priority, overdue_seconds, role_key).
            due_role_candidates: list[tuple[int, float, str]] = []

            # Identity overlays that must never be elected as due roles, even if
            # a stale role_* goal for them exists in goals.json. Mirrors the
            # _NON_SCHEDULABLE set in tools/role_manager.py.
            non_schedulable_roles = {"servo"}

            for k, v in goals_data.items():
                if v.get("type") == "finite":
                    has_due = True
                elif v.get("type") == "continuous":
                    # Skip goals pointing at non-schedulable identity overlays.
                    if k.startswith("role_") and k[5:] in non_schedulable_roles:
                        continue
                    # Skip stale role_* goals whose role no longer exists in
                    # roles.json (e.g. a renamed/removed overlay like
                    # role_manager left behind in goals.json). Without this
                    # guard the loop would elect a ghost role and the GUI
                    # would surface labels like "Manager" that don't map to
                    # any real overlay — see chat_panel._ROLE_MAP fallback.
                    if k.startswith("role_") and k[5:] not in roles:
                        continue
                    last    = v.get("last_run", 0)
                    # Coerce schedule_minutes to int. A string like "0" or "120"
                    # in goals.json (historical bug: hand-edited entries) would
                    # otherwise fall through to `"0" * 60` → string of 60 zeros,
                    # and the sched_s <= 0 comparison would raise TypeError and
                    # be caught by the outer except Exception, which silently
                    # returns has_goals=False — surfacing to the user as the
                    # misleading "Target Queue empty. Halting continuous cycle."
                    # trace. Be defensive: one bad entry should not kill the
                    # whole queue.
                    try:
                        sched_min = int(v.get("schedule_minutes", 60))
                    except (TypeError, ValueError):
                        self._trace(LoopStep.OBSERVE,
                                    f"Goal '{k}' has non-numeric schedule_minutes "
                                    f"({v.get('schedule_minutes')!r}); skipping.")
                        continue
                    sched_s = sched_min * 60
                    # A zero/negative schedule is invalid for continuous goals —
                    # treat as disabled rather than "always due" (which would
                    # pin the loop on that role forever).
                    if sched_s <= 0:
                        continue
                    remaining = sched_s - (time.time() - last)
                    if remaining <= 0:
                        has_due = True
                        if k.startswith("role_"):
                            role_key  = k[5:]  # strip 'role_' prefix
                            role_meta = roles.get(role_key, {})
                            # Default priority = 5 (lowest) for roles without an explicit field.
                            priority  = int(role_meta.get("priority", 5))
                            overdue_s = -remaining  # remaining is <=0 here, so -remaining >= 0
                            due_role_candidates.append((priority, overdue_s, role_key))
                    else:
                        min_snooze = min(min_snooze, remaining)

            # Pick deterministically: lowest priority wins, tie-break by most-overdue.
            # The winner goes into due_role; the remaining candidates — in the same
            # sort order — go into other_due_roles so the nudge can surface them as
            # "also queued" context.
            due_role = ""
            other_due_roles: list[str] = []
            if due_role_candidates:
                due_role_candidates.sort(key=lambda x: (x[0], -x[1]))
                due_role = due_role_candidates[0][2]
                other_due_roles = [c[2] for c in due_role_candidates[1:]]

            snooze_s = min_snooze if min_snooze != float("inf") else 60.0
            return True, has_due, snooze_s, due_role, other_due_roles
        except Exception:
            return False, False, 0.0, "", []

    def _call_model(self, system_prompt: str, messages: list) -> tuple:
        """
        Unified model call that handles both streaming and non-streaming modes.

        Cancellable: passes self._cancel_event down into the Ollama client so that
        setting the event (via submit_input) interrupts a mid-flight request and
        raises ChatCancelled, which the enclosing cycle catches and treats as
        "drop partial response, re-enter PERCEIVE with new user input".

        Returns:
            tuple: (content: str, truncated: bool)
        """
        if self.stream_enabled:
            self.stream_started.emit()
            raw = ""
            truncated = False
            try:
                for chunk in self.ollama.chat_stream(system_prompt, messages, cancel_event=self._cancel_event):
                    # The final yielded item is a sentinel dict with truncation info
                    if isinstance(chunk, dict) and chunk.get("done"):
                        truncated = chunk.get("truncated", False)
                    else:
                        raw += chunk
                        self.stream_chunk.emit(chunk)
            finally:
                self.stream_finished.emit()
            return raw, truncated
        else:
            return self.ollama.chat(system_prompt, messages, cancel_event=self._cancel_event)

    def _auto_continue(self, text: str, truncated: bool, system_prompt: str, messages: list, phase: str = "reason") -> str:
        """
        If the model's response was truncated by num_predict, automatically
        send a 'Continue' follow-up and concatenate the result. Up to
        self.max_auto_continues attempts to avoid infinite loops.

        phase: "reason" | "followup" — used for telemetry and for targeted
        continuation wording (tool-call JSON vs prose).
        """
        max_tries = max(0, int(self.max_auto_continues))
        for i in range(max_tries):
            if not truncated:
                break

            self.auto_continues_total += 1
            self._slog("WARNING", "core_loop", f"Response truncated by num_predict — auto-continuing ({i + 1}/{max_tries})", {
                "chars_so_far": len(text),
                "phase":        phase,
            })
            self._trace(LoopStep.REASON, f"Response truncated — auto-continuing ({i + 1}/{max_tries}) [phase={phase}]")

            # Targeted continuation: if the partial text looks like it ended mid-JSON tool-call,
            # nudge specifically for JSON completion. Otherwise use the generic continue prompt.
            stripped = text.rstrip()
            looks_like_json = (
                "```json" in stripped.lower()
                and stripped.count("{") > stripped.count("}")
            )
            if looks_like_json:
                continuation_instruction = (
                    "Your previous response was cut off mid-tool-call. "
                    "Continue the JSON block exactly where you left off and close it."
                )
            else:
                continuation_instruction = "Your previous response was cut off. Continue exactly where you left off."

            continuation_messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user",      "content": continuation_instruction},
            ]

            continuation, truncated = self._call_model(system_prompt, continuation_messages)
            text += continuation

        if truncated:
            # We exhausted auto-continues and the model is still truncating.
            self.auto_continue_give_ups_total += 1
            self._slog("WARNING", "core_loop", "Auto-continue give-up — truncation persists beyond max_auto_continues", {
                "chars_total": len(text), "phase": phase,
            })

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
                # Passive status only — the loop has already throttled conversation_history
                # for us. Do NOT nudge the model to touch system_config; that causes
                # premature self-shrink spirals.
                if self.conversation_history < self.default_conversation_history:
                    lines.append(
                        f"⚠ System throttled (RAM {ram}%, VRAM {vram}%) — "
                        f"conversation history temporarily reduced "
                        f"{self.default_conversation_history} → {self.conversation_history}."
                    )
                else:
                    lines.append(f"⚠ Hardware critical (RAM {ram}%, VRAM {vram}%).")
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

    def _load_manifest(self) -> str:
        """
        Load the canonical architecture manifest for injection into the system prompt.
        For small-context models (conversation_history <= 8), prefers
        codex/manifest_compact.json. Otherwise looks for codex/manifest.json, then
        falls back to MANIFEST.json at project root. Returns a concise, prettified
        string or "" if none exist.

        Cached by mtime so hot-edits to the manifest are picked up without restart.
        """
        import os
        prefer_compact = int(getattr(self, "conversation_history", 0) or 0) <= 8
        full_manifest    = os.path.join(os.getcwd(), "codex", "manifest.json")
        compact_manifest = os.path.join(os.getcwd(), "codex", "manifest_compact.json")
        legacy_manifest  = os.path.join(os.getcwd(), "MANIFEST.json")
        if prefer_compact and os.path.exists(compact_manifest):
            candidates = [compact_manifest, full_manifest, legacy_manifest]
        else:
            candidates = [full_manifest, compact_manifest, legacy_manifest]
        manifest_path = next((p for p in candidates if os.path.exists(p)), None)
        if manifest_path is None:
            return ""

        try:
            mtime = os.path.getmtime(manifest_path)
            if self._manifest_cache is not None and mtime == self._manifest_mtime:
                return self._manifest_cache
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rendered = json.dumps(data, indent=2)
            self._manifest_cache = rendered
            self._manifest_mtime = mtime
            return rendered
        except Exception as e:
            self._slog("WARNING", "core_loop", f"Failed to load manifest: {e}", {"path": manifest_path})
            return ""

    def _load_persona_core(self) -> str:
        """
        Load codex/persona_core.md — the canonical identity document — for
        injection into the [IDENTITY] block of the system prompt.

        Cached by mtime so hot-edits are picked up without restart.
        Strips the HTML TODO comment so it doesn't waste tokens in the prompt.
        Returns "" if the file is missing.
        """
        import os
        persona_path = os.path.join(os.getcwd(), "codex", "persona_core.md")
        if not os.path.exists(persona_path):
            return ""
        try:
            mtime = os.path.getmtime(persona_path)
            if self._persona_cache is not None and mtime == self._persona_mtime:
                return self._persona_cache
            with open(persona_path, "r", encoding="utf-8") as f:
                raw = f.read()
            # Strip HTML comments (e.g. the TODO marker) so we don't pay tokens for them
            rendered = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()
            self._persona_cache = rendered
            self._persona_mtime = mtime
            return rendered
        except Exception as e:
            self._slog("WARNING", "core_loop", f"Failed to load persona_core: {e}", {"path": persona_path})
            return ""

    def _load_role_manifest(self, role_key: str) -> str:
        """
        Load codex/role_manifests/<role_key>.md — the human-language role
        briefing — for injection into the [ROLE BRIEFING] block when the
        corresponding role is the active overlay.

        Historical note: these manifests existed on disk for months but were
        read by zero lines of Python; the model's picture of "what this role
        does" was just the single `task` line in roles.json. This loader is
        what makes hand-editing the markdown actually land in context.

        Cached per-role by mtime so hot-edits are picked up without restart.
        Returns "" if the file is missing, unreadable, or empty after
        stripping HTML comments.
        """
        import os
        if not role_key or role_key == "servo":
            # servo is the no-overlay default identity; it has no briefing.
            return ""
        manifest_path = os.path.join(os.getcwd(), "codex", "role_manifests", f"{role_key}.md")
        if not os.path.exists(manifest_path):
            return ""
        try:
            mtime = os.path.getmtime(manifest_path)
            cached = self._role_manifest_cache.get(role_key)
            if cached is not None and mtime == self._role_manifest_mtime.get(role_key, 0):
                return cached
            with open(manifest_path, "r", encoding="utf-8") as f:
                raw = f.read()
            # Strip HTML comments so editorial TODOs don't leak into the prompt.
            rendered = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()
            self._role_manifest_cache[role_key] = rendered
            self._role_manifest_mtime[role_key] = mtime
            return rendered
        except Exception as e:
            self._slog("WARNING", "core_loop", f"Failed to load role manifest: {e}", {"path": manifest_path})
            return ""

    def _get_active_overlay(self) -> dict:
        """
        Return the overlay metadata for the currently active role. If no role
        is active (normal conversational mode), return the 'servo' default
        overlay. Returns {} if neither exists.
        """
        roles = self._load_roles()
        key = self._active_role if self._active_role else "servo"
        overlay = roles.get(key, {})
        if not overlay and key != "servo":
            # Role unknown — fall back to servo default
            overlay = roles.get("servo", {})
        return overlay

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
        # Render the workspace and codex locations as PROJECT-ROOT-RELATIVE
        # paths (D-20260417-09). Showing absolute Windows paths here trained
        # the model to emit absolute paths back into tool args, which was
        # then hallucinated into mangled user segments like
        # `C:/Users/iam/OneDrive/...`. Tools now reject absolute paths; the
        # prompt must not contradict the rule by showing them.
        workspace_folder = f"workspace/{model_safe_name}"
        codex_folder     = "codex"

        # Roles are loaded once here so we can resolve live task text for
        # role_* continuous goals. Historically, role_manager.enable() froze
        # `[title] task` into goals.json at enable-time, which meant editing
        # the task field in roles.json never propagated until a
        # disable/enable cycle. We now treat roles.json as the single source
        # of truth and look up role descriptions fresh each build.
        roles_live = self._load_roles()

        def _goal_description(goal_key: str, goal_meta: dict) -> str:
            """Return the description to render for a goal. For role_* goals,
            prefer the live roles.json entry; fall back to the frozen copy in
            goals.json only if the role was removed from roles.json."""
            if goal_key.startswith("role_"):
                role_key = goal_key[len("role_"):]
                role = roles_live.get(role_key)
                if role:
                    title = role.get("title", role_key)
                    task  = (role.get("task") or "").strip()
                    if task:
                        return f"[{title}] {task}"
            return goal_meta.get("description", "")

        goals_text = ""
        try:
            goal_path = os.path.join(os.getcwd(), "goals.json")
            if os.path.exists(goal_path):
                with open(goal_path, "r", encoding="utf-8") as f:
                    gls = json.load(f)
                    if gls:
                        # Split the queue so we can render each list with
                        # mode-aware language. When Continuous Mode is OFF,
                        # continuous role goals are NOT actionable by the
                        # model — the user drives each turn — so the prompt
                        # must NOT say "DUE NOW - Please execute ..." for
                        # them. Historically that wording trained the model
                        # to elect itself into a role on unrelated user
                        # turns (e.g. ask a simple question on reboot, model
                        # invokes scholar_runner because the prompt said
                        # the Scholar goal was due). Visibility is still
                        # preserved with an inert "Scheduled every Nm" label.
                        finite_items     = [(k, v) for k, v in gls.items() if v.get("type") == "finite"]
                        continuous_items = [(k, v) for k, v in gls.items() if v.get("type") == "continuous"]

                        goals_text += "\n\n[ACTIVE GOALS]"
                        if self.continuous_mode:
                            goals_text += "\nCRITICAL: You must execute FINITE goals (Priority 1) completely using tools before actively working on CONTINUOUS routines (Priority 2)."
                        elif finite_items:
                            goals_text += "\nCRITICAL: Execute FINITE goals (Priority 1) completely using tools. Continuous Mode is OFF — continuous role goals below are listed for visibility only; you MUST NOT elect yourself into one on a user turn or invoke their auto-tools unprompted."
                        else:
                            goals_text += "\nContinuous Mode is OFF. The goals below are listed for visibility only — they only fire when Continuous Mode is enabled and the loop auto-prods you. You MUST NOT elect yourself into a role on a user turn or invoke their auto-tools unprompted."

                        for k, v in finite_items:
                            desc = _goal_description(k, v)
                            expires_at = v.get("expires_at")
                            if expires_at:
                                mins_left = max(0, int((expires_at - time.time()) / 60))
                                goals_text += f"\n  - [FINITE PRIORITY 1] {k}: {desc} (Auto-expires in {mins_left} min)"
                            else:
                                goals_text += f"\n  - [FINITE PRIORITY 1] {k}: {desc}"
                        for k, v in continuous_items:
                            desc = _goal_description(k, v)
                            last_run  = v.get("last_run", 0)
                            try:
                                sched_min = int(v.get("schedule_minutes", 60))
                            except (TypeError, ValueError):
                                sched_min = 60
                            sched_sec = sched_min * 60
                            if not self.continuous_mode:
                                # Inert label — no action verb, no "DUE NOW".
                                goals_text += f"\n  - [CONTINUOUS PRIORITY 2] {k}: {desc} (Scheduled every {sched_min} min — Continuous Mode OFF, will not fire)"
                                continue
                            time_since = time.time() - last_run
                            if time_since >= sched_sec:
                                goals_text += f"\n  - [CONTINUOUS PRIORITY 2] {k}: {desc} (DUE NOW - Please execute and call goal_manager mark_done)"
                            else:
                                snooze_min = int((sched_sec - time_since) / 60)
                                goals_text += f"\n  - [CONTINUOUS PRIORITY 2] {k}: {desc} (Snoozing for {snooze_min} more minutes)"
        except Exception:
            pass

        manifest_text = self._load_manifest()
        manifest_block = f"\n\n[SYSTEM ARCHITECTURE]\n{manifest_text}" if manifest_text else ""

        # ── Persona layer (identity + active overlay) ──
        persona_text = self._load_persona_core()
        identity_block = f"\n[IDENTITY]\n{persona_text}\n" if persona_text else ""

        overlay = self._get_active_overlay()
        overlay_key = self._active_role if self._active_role else "servo"
        if overlay:
            voice = overlay.get("voice_overlay", "")
            fmt   = overlay.get("format_bias", "")
            risk  = overlay.get("risk_tolerance", "")
            title = overlay.get("title", overlay_key)
            domain = overlay.get("domain", "")
            overlay_lines = [f"\n[ACTIVE ROLE] {title}"]
            if domain:
                overlay_lines.append(f"Domain: {domain}")
            if voice:
                overlay_lines.append(f"Voice: {voice}")
            if fmt:
                overlay_lines.append(f"Format bias: {fmt}")
            if risk:
                overlay_lines.append(f"Risk tolerance: {risk}")
            overlay_lines.append(
                "This overlay modulates voice and emphasis only. The IDENTITY above is invariant."
            )
            overlay_block = "\n" + "\n".join(overlay_lines) + "\n"
        else:
            overlay_block = ""

        # Role briefing: full human-language manifest for the active role,
        # drawn from codex/role_manifests/<role>.md. Only injected when a
        # role is active (overlay_key != "servo") so inactive roles don't
        # bloat the default conversational context. The manifest owns the
        # narrative — what the role's auto-tool does, what the model is
        # expected to do after the tool runs, how to tell when the role is
        # finished for the cycle. roles.json still owns the machine fields
        # (schedule, priority, voice_overlay, format_bias, risk_tolerance).
        briefing_block = ""
        if overlay_key and overlay_key != "servo":
            briefing_text = self._load_role_manifest(overlay_key)
            if briefing_text:
                briefing_block = f"\n[ROLE BRIEFING]\n{briefing_text}\n"

        # Phase 2 (D-20260419-01): inject the active conversation
        # summary (if any) as a [PRIOR CONTEXT] block. The block sits
        # between [ROLE BRIEFING] and [SYSTEM ENVIRONMENT] so it reads
        # as "here's what you already remember" immediately after
        # identity and role scaffolding, before environment/policy
        # details. The raw turns covered by this summary are filtered
        # out of the Ollama message list in `_build_messages` — the
        # summary and the raw turns never travel together.
        prior_context_block = ""
        history_summary = context.get("history_summary") if context else None
        if history_summary and history_summary.get("summary"):
            prior_context_block = (
                "\n[PRIOR CONTEXT]\n"
                "The turns below the live exchange have been compressed into "
                "the following summary. Treat it as your own memory of those "
                "turns — do not ask Kevin to repeat decisions or requests "
                "captured here.\n\n"
                f"{history_summary['summary']}\n"
            )

        base = f"""You are Servo — an autonomous local-AI executive layer with access to tools and persistent memory.
{identity_block}{overlay_block}{briefing_block}{prior_context_block}
[SYSTEM ENVIRONMENT]
Model Identity: {self.ollama.model}
Temperature: {self.ollama.temperature}
Max Tokens: {self.ollama.num_predict}
Conversation History: {self.conversation_history} turns{manifest_block}

[WORKING MEMORY]
{working_memory if working_memory else "Empty. Use memory_manager tool to document persistent goals or project logic."}

[WORKSPACE POLICY]
For security, your filesystem access (both READ and WRITE) is strictly sandboxed to the local project root.

You have WRITE permission in two places:

1. Your model-scoped scratch workspace (use this by default for proposals, critiques, snapshots, screenshots, calibration runs):
   -> {workspace_folder}
   If this folder does not exist yet, you are authorized to create it using your tools.

2. The Codex (canonical project truth) — `codex/`:
   -> {codex_folder}
   You may write to the Codex when maintaining the canonical docs that belong to your role. Any role may append to `codex/decisions.md` and `codex/history.md`. The Orchestrator proposes updates to `codex/skill_map.md` and entries under `codex/role_manifests/` via change proposals — it does not edit them directly. The Scholar maintains `workspace/<model>/architecture_review_<v>.md` (bumping the prior version to `workspace/<model>/old_stuff/` each cycle), not a Codex file. `codex/persona_core.md` is hand-edited by Kevin only — do not modify it without an explicit instruction.

Editing convention for the Codex: prefer in-place updates over creating new variant files. If you propose a structural change to a Codex doc, write the proposal into your scratch workspace first (as `change_proposal_<ID>.md`) and let the Analyst critique it before promoting.

Do not write outside the project root.

[PATH DISCIPLINE]
All path arguments to tools are PROJECT-ROOT-RELATIVE. The project root is managed by the tool — you never emit it.
  - CORRECT:   `codex/manifest.json`, `tools/log_query.py`, `workspace/{model_safe_name}/notes.md`
  - REJECTED:  `C:/Users/.../codex/manifest.json`, `/home/.../tools/log_query.py`, any path starting with a drive letter or leading slash
Absolute paths are rejected with an error — there is no recovery, no fuzzy matching. If you see "Absolute paths are not allowed" in a tool result, re-issue the call with the project-root-relative form.
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
            base += f" Maximum chained tool calls this turn: {self.chain_limit}."
        else:
            if self.autonomous_loop_limit > 0:
                base += (
                    f" Continuous Mode is ACTIVE (autonomous-loop cap: {self.autonomous_loop_limit}). "
                    f"Keep chaining tools until all finite goals are cleared or the cap is hit."
                )
            else:
                base += " Continuous Mode is ACTIVE. Keep chaining tools endlessly to loop until all finite goals are cleared."

        # If the model is generating followup during the final allowed chain step, physically constrain its behaviour
        if is_followup and (current_loop + 1 >= self.chain_limit) and not self.continuous_mode:
            base += "\n[SYSTEM STATUS] Note: The chain limit has been reached. If you output a tool request now, it will not execute automatically. It will pause for user review."

        if is_followup:
            if self.verbosity == "Concise":
                base += "\n5. Provide a very concise, direct 1-sentence summary of your actions."
            elif self.verbosity == "Detailed":
                base += "\n5. Exhaustively explain your logic and findings step-by-step."
                
        base += f"\n\nMEMORY:{memory_lines if memory_lines else ' Empty.'}"
        return base

    def _build_messages(self, context: dict) -> list:
        messages = []

        # Phase 2 (D-20260419-01): if a conversation summary is active,
        # skip history turns whose id is already covered by it — the
        # summary is being rendered as [PRIOR CONTEXT] in the system
        # prompt, so sending those turns again would duplicate the
        # signal and eat context budget we just spent to compress.
        summary = context.get("history_summary")
        covers_to_id = int(summary["covers_to_id"]) if summary else 0

        for t in context.get("history", []):
            # Turns predating the Phase-2 schema change do not carry an
            # id. They shouldn't exist in a fresh DB but guard anyway —
            # include them unfiltered rather than drop real history.
            turn_id = t.get("id")
            if turn_id is not None and turn_id <= covers_to_id:
                continue
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
