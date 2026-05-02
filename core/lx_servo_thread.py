# lx_servo_thread.py
#
# Phase E (UPGRADE_PLAN_4 sec 6) -- Qt adapter that wraps `ServoCore`
# in the QThread + signal surface `gui/main_window.py` expects of
# `core.loop.CoreLoop`. ServoCore itself stays plain (the headless
# benchmark path runs without PySide6 installed); this thread is the
# GUI-facing wrapper that satisfies the same Qt contract under the
# `USE_SERVO_CORE` toggle.
#
# The signal surface mirrors `CoreLoop` 1:1 so `main_window._connect_signals`
# can attach to either object without branching. Most signals will be
# present-but-quiescent under the Servo path -- the cognate dispatch
# loop does not yet emit `stream_chunk` / `telemetry_event` /
# `context_view_requested` (those are Phase F's concern, per §6.3 of
# the plan). The signals exist so consumers don't crash on connect;
# the emitting side is a no-op until Phase F wires the cognate
# logging channel into them.
#
# Mutable knob attributes (`conversation_history`, `chain_limit`, ...)
# exist as class-level defaults so `main_window`'s settings panel can
# write to them without AttributeError. They are read by no part of
# the cognate loop in Phase E -- the cognates pull tunables from
# `self.core.config.get(...)` (ConfigRegistry).
#
# A new `tool_dispatched(tool_name: str)` signal is defined here per
# UPGRADE_PLAN_4 sec 6.2 so `gui/tool_panel.py` can highlight the
# active row. Emission is wired from `lx_Act` via a callback hook on
# the wrapper.
#
# Rollback: setting `SERVO_CORE=0` (or `use_servo_core: false` in
# config) restores the legacy `CoreLoop` construction path. This file
# is never imported on that path.

from __future__ import annotations

import json
import time
import traceback
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.core import ServoCore
from core.lx_state import lx_StateStore


class ServoCoreThread(QThread):
    """Qt-thread shell that drives a `ServoCore` for the GUI.

    Construction signature mirrors `CoreLoop.__init__(state, ollama, tools)`
    so `main_window` can swap the constructor with a one-line branch.
    """

    # ------------------------------------------------------------------
    # Signal surface -- 1:1 with CoreLoop. Connect points in main_window
    # bind to these by name; types/arity must match.
    # ------------------------------------------------------------------
    step_changed             = Signal(str)
    trace_event              = Signal(str, str)
    response_ready           = Signal(str, str)
    tool_called              = Signal(str, str, str)
    error_occurred           = Signal(str)
    stream_chunk             = Signal(str)
    stream_started           = Signal()
    stream_finished          = Signal()
    config_changed           = Signal(str, object)
    log_event                = Signal(str, str, str, str)
    telemetry_event          = Signal(int, int)
    context_view_requested   = Signal(list)

    # New in Phase E (UPGRADE_PLAN_4 sec 6.2) -- emitted right before
    # lx_Act dispatches a tool, so the tool panel can highlight the
    # active row. Listener side: `gui/tool_panel.py`.
    tool_dispatched          = Signal(str)

    # ------------------------------------------------------------------
    # Mutable knobs the settings panel writes to. Defaults match the
    # CoreLoop defaults so the GUI reads the same baseline values
    # regardless of which engine is active.
    # ------------------------------------------------------------------
    conversation_history          = 0
    default_conversation_history  = 0
    chain_limit                   = 3
    autonomous_loop_limit         = 0
    max_auto_continues            = 2
    verbosity                     = "Normal"
    stream_enabled                = True
    hardware_throttling_enabled        = False
    hardware_throttle_threshold_enter  = 85.0
    hardware_throttle_threshold_exit   = 70.0

    # Telemetry counters that context_dump / loop_panel may read via
    # getattr. They never increment under the Servo path in Phase E;
    # the values mirror a fresh CoreLoop boot.
    truncations_total                = 0
    followup_truncations_total       = 0
    auto_continues_total             = 0
    auto_continue_give_ups_total     = 0
    hardware_throttle_total          = 0
    user_interrupts_total            = 0
    history_compressions_total       = 0
    tool_result_compressions_total   = 0

    def __init__(self, state, ollama=None, tools=None, config=None, parent=None):
        super().__init__(parent)

        # ServoCore is the real work surface. We keep it plain (no Qt
        # inheritance) so the headless benchmark path stays valid.
        self._core = ServoCore(ollama=ollama, config=config)
        self._state = state
        self._tools = tools

        # Expose ollama and state on the thread so GUI-facing tools
        # (system_config, context_dump, etc.) that duck-type
        # `loop.ollama.*` and `loop.state.*` keep working.
        self.ollama = ollama
        self.state = state

        # Phase F hotfix (D-20260427) -- the legacy `core.state.StateStore`
        # passed in by `gui/main_window.py` is a key/value SQLite + Chroma
        # store the GUI uses for its settings panel. The cognate loop
        # needs the Phase C `lx_StateStore` (Sovereign Ledger) which
        # exposes `get_active_profile()` / `apply_delta()`. We construct
        # one here, mirroring the legacy store's profile so per-profile
        # JSON mirror + procedural_wins land under the right namespace.
        # The legacy `self._state` stays around so the GUI's existing
        # `state.get(...)` / `state.set(...)` calls keep working.
        try:
            profile = getattr(state, "profile", None) or "lx_default"
        except Exception:
            profile = "lx_default"
        self._lx_state = lx_StateStore(
            profile=str(profile),
            config=self._core.config,
        )

        # Expose .config so `self.tools.config = self.loop.config` in
        # main_window resolves to the same ConfigRegistry the cognates
        # see. This is the GUI's primary read of the registry.
        self.config = self._core.config

        # Wire the config registry's persistence and live-injection
        # references so system_config.set() and profile loads work.
        self.config.bind_state(state)
        self.config.bind_loop(self)

        # Run-control flags. The cognate loop runs synchronously inside
        # ServoCore.run_cycle; our QThread.run() supervises it and
        # honors stop/pause requests between cycles.
        self._stop_requested = False
        self._pause_requested = False
        self._is_paused = False

        # Phase F (UPGRADE_PLAN_5 sec 6) -- the perception queue moved
        # onto ServoCore. ServoCoreThread no longer holds inputs locally;
        # `submit_input` forwards into `self._core.submit_perception`,
        # which OBSERVE pops on its next park/wake cycle. We keep a
        # shadow list on the wrapper purely as a debug tap so a GUI
        # widget that wants to display "what we sent" can read it
        # without locking the cognate's condition.
        self._pending_inputs: list = []

        # Wire the tool-dispatch hook on lx_Act if the cognate is
        # cooperative. Best-effort -- a future cognate refactor that
        # drops the attribute is not a boot-time error.
        try:
            act = self._core.registry.get("ACT")
            if act is not None:
                # The hook is a plain callable; lx_Act calls it (when
                # set) right before invoking the registry. A missing
                # hook is treated as no-op by lx_Act.
                setattr(act, "_lx_dispatch_hook",
                        lambda tool_name: self.tool_dispatched.emit(str(tool_name or "")))
        except Exception:
            # Defensive -- adapter install failing is not a boot-time
            # error. The signal stays defined; emission just won't fire.
            pass

        # Phase F (UPGRADE_PLAN_5 sec 6) -- bind ServoCore's
        # response_ready_hook to the Qt signal so REASON's prose lands
        # in the chat panel. The hook is invoked from lx_Integrate;
        # we wrap the emit in a defensive lambda so a Qt teardown
        # race (signals after the thread is gone) doesn't surface as
        # a cognate-side traceback.
        try:
            self._core.response_ready_hook = (
                lambda text, image="", _self=self:
                _self.response_ready.emit(str(text or ""), str(image or ""))
            )
        except Exception:
            # Defensive -- if response_ready_hook isn't on the core
            # (older ServoCore version) we just skip wiring.
            pass

        # Wire telemetry_hook to surface token usage
        try:
            self._core.telemetry_hook = (
                lambda current, limit, _self=self:
                _self.telemetry_event.emit(current, limit)
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CoreLoop-compatible public methods
    # ------------------------------------------------------------------
    def submit_input(self, text: str, image_b64: str = ""):
        """Forward user input as a perception event into ServoCore.

        Phase F (UPGRADE_PLAN_5 sec 6) -- the perception queue lives on
        ServoCore now. We package the input as a `kind="user_input"`
        event and call `submit_perception`, which appends to the queue
        and notifies the OBSERVE park. The trace_event keeps the GUI
        log honest about what was received, but the polite "wired in
        Phase F" stub is gone -- the cognate loop owns the dispatch.
        """
        event = {
            "kind": "user_input",
            "text": text or "",
            "image_b64": image_b64 or "",
            "timestamp": time.time(),
        }
        # Local debug tap (see __init__ comment) -- mirrored copy with
        # the same fields the cognate sees. Bounded at 64 entries so a
        # long-running session doesn't bloat the wrapper.
        self._pending_inputs.append(dict(event))
        if len(self._pending_inputs) > 64:
            self._pending_inputs = self._pending_inputs[-64:]

        self.trace_event.emit(
            "PERCEIVE",
            f"[Servo path] Input received: {len(text or '')} chars",
        )

        # Hand the event off to ServoCore. submit_perception is a quick
        # append + notify_all under the condition; it does not block
        # on cognate work.
        try:
            self._core.submit_perception(event)
        except Exception as e:
            # Defensive -- a bug in the cognate's queue shouldn't
            # crash the GUI thread. Surface it as an error event so
            # the user can see what happened, then drop the input.
            self.error_occurred.emit(
                f"[Servo path] submit_perception failed: "
                f"{type(e).__name__}: {e}"
            )

    def submit_startup_diagnostic(self, text: str):
        self.trace_event.emit("PERCEIVE", "[Servo path] Startup diagnostic received")

    def stop(self):
        # Phase F (UPGRADE_PLAN_5 sec 6) -- propagate the halt into
        # ServoCore.halt_event so a parked OBSERVE wakes up and breaks
        # out instead of waiting on a perception that will never
        # arrive. The legacy `_stop_requested` flag stays set so the
        # apply_delta watchdog also injects `halt=True` on the next
        # cycle boundary as a belt-and-suspenders break.
        self._stop_requested = True
        try:
            self._core.signal_halt()
        except Exception:
            # Best-effort; a missing signal_halt (e.g. very old core)
            # falls back to the watchdog path.
            pass

    def cleanup(self):
        self._stop_requested = True
        try:
            self._core.signal_halt()
        except Exception:
            pass
        # Clear the dirty flag on graceful shutdown so the next boot
        # can distinguish a crash from a normal exit.
        try:
            if hasattr(self._state, 'set_session_flag'):
                self._state.set_session_flag('dirty', 'False')
        except Exception:
            pass

    def resume(self):
        self._pause_requested = False
        self._is_paused = False

    def wait_if_paused(self):
        # Symmetric with CoreLoop.wait_if_paused; called by external
        # widgets that want to coordinate with a paused loop. We honor
        # it by spinning until resume() flips the flag.
        while self._is_paused and not self._stop_requested:
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # QThread.run -- supervises ServoCore.run_cycle.
    # ------------------------------------------------------------------
    def run(self):
        """Drive `ServoCore.run_cycle` against the supplied state store.

        The cognate loop in ServoCore is itself a `while True` that
        breaks on `state["halt"]` or unknown step. We wrap it so a
        crash inside a cognate emits `error_occurred` for the GUI
        rather than tearing down the thread silently, and so
        `stop()` can flip a halt flag the next cycle observes.
        """
        try:
            self.step_changed.emit("OBSERVE")
            self.trace_event.emit("OBSERVE", "[Servo path] CIRCUIT CLOSED. SERVO ACTIVE.")

            # ── Restart-reason detection (ported from CoreLoop D-20260421-14) ──
            reason = self._detect_restart_reason()
            boot_ts = time.strftime("%Y-%m-%d %H:%M:%S")
            restart_text = (
                f"--- SYSTEM RESTART ---\n"
                f"Timestamp: {boot_ts}\n"
                f"Reason: {reason}\n\n"
                "Session suspended. Booting new session. All prior volatile state, "
                "open file offsets, and unconfirmed commands have been wiped. "
                "Review your workspace and task list before continuing."
            )

            # Inject the restart notice as the first perception so REASON
            # sees it on the very first cycle and knows it was restarted.
            try:
                self._core.submit_perception({
                    "kind": "user_input",
                    "text": f"[SYSTEM REFERENCE ONLY: STARTUP DIAGNOSTICS]\n{restart_text}\n[END REFERENCE - NO ACTION REQUIRED]",
                    "_transient": True,
                    "type": "system",
                    "timestamp": time.time(),
                })
            except Exception:
                pass

            # Set the dirty flag so a crash before cleanup() is detectable.
            try:
                if hasattr(self._state, 'set_session_flag'):
                    self._state.set_session_flag('dirty', 'True')
            except Exception:
                pass

            # Best-effort halt-injection wrapper around the state store
            # so `stop()` propagates into the cognate loop. If the
            # store doesn't expose `apply_delta`, we just call
            # run_cycle directly and rely on `halt` being set
            # externally.
            #
            # Phase F hotfix (D-20260427) -- pass the cognate-owned
            # lx_StateStore (constructed in __init__), not the legacy
            # key/value StateStore the GUI uses for its settings panel.
            # The legacy store has no `get_active_profile`, which is
            # what the AttributeError on this line was reporting.
            store = self._lx_state
            try:
                if hasattr(store, "apply_delta"):
                    original_apply = store.apply_delta

                    def _watchdog_apply(delta, _orig=original_apply, _self=self):
                        d = delta or {}
                        if isinstance(d, dict) and "current_step" in d:
                            _self.step_changed.emit(d["current_step"])
                            
                        if _self._stop_requested:
                            d = dict(d)
                            d["halt"] = True
                            return _orig(d)
                        return _orig(delta)

                    store.apply_delta = _watchdog_apply
            except Exception:
                pass

            self._core.run_cycle(store)

            self.step_changed.emit("OBSERVE")
            self.trace_event.emit("OBSERVE", "[Servo path] Loop terminated cleanly.")
        except Exception as e:
            tb = traceback.format_exc()
            self.error_occurred.emit(f"[Servo path] {type(e).__name__}: {e}\n{tb}")


    # ------------------------------------------------------------------
    # Restart-reason detection (ported from CoreLoop D-20260421-14).
    # ------------------------------------------------------------------
    def _detect_restart_reason(self) -> str:
        """Determine why the system is rebooting.

        Priority order:
          1. CODE_DEPLOYMENT — core/ directory modified in the last 3 min.
          2. FAILURE_RECOVERY — session_dirty was True (non-graceful exit).
          3. STANDARD_BOOT — normal initialization.
        """
        import os

        # 1. Code deployment check
        try:
            core_dir = os.path.dirname(os.path.abspath(__file__))
            mtime = os.path.getmtime(core_dir)
            if (time.time() - mtime) < 180:  # 3-minute window
                return "CODE_DEPLOYMENT (Internal logic update detected)"
        except Exception:
            pass

        # 2. Dirty-shutdown check
        try:
            if hasattr(self._state, 'get_session_flag'):
                is_dirty = self._state.get_session_flag('dirty', 'False') == 'True'
                if is_dirty:
                    return "FAILURE_RECOVERY (Non-graceful termination detected)"
        except Exception:
            pass

        return "STANDARD_BOOT (Normal initialization)"


__all__ = ["ServoCoreThread"]
