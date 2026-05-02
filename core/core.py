# core.py
import threading
import time as _time
from collections import deque

from core.lx_cognates import (
    lx_Observe, lx_Reason, lx_Act, lx_Integrate,
    ATOMIC_PRIMITIVES as _LX_ATOMIC_PRIMITIVES,
)
from core.config_registry import ConfigRegistry

class ServoCore:
    """The Main Execution Engine for the Servo Core Upgrade."""

    # Phase E (UPGRADE_PLAN_4 sec 6, Q5) -- expose the eleven Phase D
    # atomic primitives as a public frozenset so consumers (notably
    # gui/tool_panel.py) can read the dispatch surface directly off
    # ServoCore rather than reaching into core.lx_cognates. Ordering
    # is not part of the contract -- callers must not rely on a
    # specific iteration order. The underlying tuple lives in
    # lx_cognates.ATOMIC_PRIMITIVES; this is just a frozen view.
    ATOMIC_PRIMITIVES: frozenset = frozenset(_LX_ATOMIC_PRIMITIVES)

    def __init__(self, ollama=None, config=None):
        # Phase E (UPGRADE_PLAN_4 sec 4): ConfigRegistry is the single
        # source of truth for the seven Phase D literals. A caller may
        # pass an explicit registry (e.g. the GUI with a pre-loaded
        # overlay); otherwise we instantiate the default, which reads
        # codex/manifests/config.json or falls through to _DEFAULTS when
        # that file is absent. Exposed on self so Cognates reach it via
        # self.core.config.get(...).
        self.config = config if config is not None else ConfigRegistry()

        # Initialize the Polymorphic Registry
        # These keys must exactly match the 'current_step' returned by Cognates
        self.registry = {
            "OBSERVE": lx_Observe(self),
            "REASON": lx_Reason(self),
            "ACT": lx_Act(self),
            "INTEGRATE": lx_Integrate(self)
        }
        # Optional Ollama client for lx_Integrate embedding commits and for
        # LxLoopAdapter.ollama pass-through. None is tolerated -- the
        # dependent paths degrade gracefully.
        self.ollama = ollama

        # Phase E -- prior env_audit snapshot. Originally introduced for
        # `lx_Reason._observation_signal` drift detection (UPGRADE_PLAN_4
        # sec 7). Phase G (UPGRADE_PLAN_6 sec 3e) deleted that classifier
        # in favor of ChromaDB env_snapshots similarity, so this field is
        # currently used only by lx_Integrate's diff-based logging. We
        # keep writing it on every successful cycle so a future Phase H+
        # consumer (e.g. drift telemetry) can pick it up without
        # plumbing changes; if no consumer materializes the field can
        # be retired. Survives across `run_cycle` invocations within a
        # single ServoCore lifetime; cleared by a fresh __init__.
        self._prior_audit_snapshot = None

        # Phase F (UPGRADE_PLAN_5 sec 6) -- perception queue + condition
        # variable so OBSERVE can park between user inputs instead of
        # spinning. Ownership is on ServoCore (not on the Qt thread
        # wrapper) so headless callers -- benchmarks, unit tests, the
        # legacy CLI bridge -- can submit perceptions without dragging
        # PyQt in. The contract is single-producer-single-consumer in
        # the common case (GUI submits, OBSERVE consumes); the lock is
        # there to keep the wait/notify edge correct, not to support
        # multi-consumer fanout.
        #
        #   perception_queue   - FIFO of perception event dicts. Each
        #                        event is a plain dict with at least
        #                        {"kind": "user_input"|"tool_output",
        #                         "timestamp": float} plus per-kind
        #                        fields (text, image_b64, tool_result,
        #                        ...). lx_Observe pops the head when it
        #                        wakes; producers append to the tail.
        #   perception_cond    - threading.Condition guarding the queue.
        #                        OBSERVE acquires it to peek/pop and to
        #                        wait when the queue is empty. Producers
        #                        acquire it briefly to append + notify.
        #   halt_event         - threading.Event set by signal_halt().
        #                        OBSERVE checks it each wake-up so a
        #                        Stop button click breaks the park
        #                        without needing to enqueue a sentinel.
        self.perception_queue = deque()
        self.perception_cond = threading.Condition()
        self.halt_event = threading.Event()

        # Phase F (UPGRADE_PLAN_5 sec 6) -- response_ready_hook is the
        # cognate-loop -> chat layer surface. lx_Integrate calls this
        # whenever REASON emitted prose, with shape (text, image_b64).
        # The Qt thread wrapper sets it during construction so the
        # response flows out as a `response_ready` signal; headless
        # callers (benchmarks, unit tests) leave it None and the
        # cognate loop runs silently. We hold a single callable here
        # rather than a list -- multi-listener fanout is a Phase G+
        # concern if it ever materializes.
        self.response_ready_hook = None
        
        # Telemetry hook for tracking token usage.
        self.telemetry_hook = None

    # ------------------------------------------------------------------
    # Phase F (UPGRADE_PLAN_5 sec 6) -- perception ingest surface.
    # ------------------------------------------------------------------
    def submit_perception(self, event):
        """Append a perception event and wake any parked OBSERVE.

        ``event`` is a plain dict shaped like:
            {"kind": "user_input"|"tool_output",
             "timestamp": float,
             ...kind-specific payload}

        Producers (GUI submit_input, ACT cross-cycle followup) call
        this; lx_Observe.execute consumes from the head. The condition
        is held only briefly -- append + notify_all -- so the producer
        never blocks on a slow consumer. ``notify_all`` is fine because
        we expect at most one OBSERVE waiting, but a future fanout
        (mirror, telemetry tap) wouldn't need a code change here.
        """
        if not isinstance(event, dict):
            raise TypeError(
                f"submit_perception expects dict, got {type(event).__name__}"
            )
        if "kind" not in event:
            raise ValueError("submit_perception event missing 'kind' field")
        # Stamp a timestamp if the producer didn't -- OBSERVE sorts by
        # arrival order via the deque, but downstream telemetry reads
        # ``timestamp`` for cycle-budget bookkeeping.
        event.setdefault("timestamp", _time.time())
        with self.perception_cond:
            self.perception_queue.append(event)
            self.perception_cond.notify_all()

    def signal_halt(self):
        """Set halt_event and wake any parked OBSERVE.

        The Stop button on the GUI calls this through ServoCoreThread.
        OBSERVE re-checks halt_event after each wake-up, so this is
        sufficient to break the park even when the queue stays empty.
        We notify under the same condition the queue uses so the
        wake-up edge is monotonic with respect to enqueues.
        """
        self.halt_event.set()
        with self.perception_cond:
            self.perception_cond.notify_all()

    def run_cycle(self, state_provider):
        """The Main Execution Loop."""
        # D-20260423 (Phase C): Stash the active store on self so Cognates can
        # reach procedural_wins / legacy config via self.core._active_store.
        # Scoped to the run_cycle lifetime -- cleared when the loop breaks so
        # a later cycle can't accidentally inherit a stale handle.
        self._active_store = state_provider
        # Phase E (UPGRADE_PLAN_4 sec 4): if the active store was built
        # without a config (common for benchmarks and tests that predate
        # Phase E), attach ours so the store's _cfg_get helper can resolve
        # tunables. We only attach when the store has no config of its
        # own -- a caller-supplied config wins.
        try:
            if getattr(state_provider, "_config", None) is None:
                state_provider._config = self.config
        except Exception:
            # Best-effort -- a non-standard store (legacy shim target,
            # test double) that rejects setattr is not a run-cycle blocker.
            pass
        print("[SYSTEM] CIRCUIT CLOSED. SERVO ACTIVE.")

        # Phase G (UPGRADE_PLAN_6 sec 1, D-20260427-01) -- the
        # `core/lx_loop_shim.py` install/uninstall scaffolding was
        # deleted with the shim file. Both jobs the shim used to do
        # have already moved to per-dispatch injection: (a) sqlite3
        # routing now flows through `tool_context.conn_factory`
        # (Phase E, D-20260424-01) and (b) `_get_loop_ref` adapter
        # delivery flows through `tool_context.legacy_loop_ref`
        # (Phase F, D-20260426-01). No cycle-scoped patches, no
        # finally-block uninstall, and no `_lx_shim_handle` attribute.

        try:
            # v2.0: The stateless loop that processes the Sovereign Ledger
            while True:
                # Phase F (UPGRADE_PLAN_5 sec 8) -- hot-reload tunables at
                # the top of each cycle. ConfigRegistry.maybe_reload()
                # is one stat() call when the mtime is unchanged, so the
                # cost is negligible. A successful reload propagates to
                # any caller reading via self.config.get(...) on the
                # next access; existing in-flight cognate frames keep
                # the value they read at frame start, which avoids the
                # mid-cycle mismatch a snapshot-by-cycle policy is meant
                # to prevent. Best-effort; a config without a registry
                # (legacy boot path that constructed ServoCore with
                # config=None? defensive only -- __init__ always builds
                # one) just skips.
                cfg = getattr(self, "config", None)
                if cfg is not None and hasattr(cfg, "maybe_reload"):
                    try:
                        cfg.maybe_reload()
                    except Exception:
                        # A malformed config file should not crash the
                        # cognate loop. ConfigRegistry already swallows
                        # parse errors internally; this is belt-and-
                        # suspenders for any future reload hook.
                        pass

                # 1. Pull current state from the decoupled Ledger
                current_state = state_provider.get_active_profile()
                step_key = current_state.get("current_step", "OBSERVE")

                # 2. Dispatch Cognate from the Polymorphic Registry
                cognate = self.registry.get(step_key)
                if not cognate:
                    print(f"[ERROR] UNKNOWN COGNATE: {step_key}. ABORTING CIRCUIT.")
                    break

                # 3. Execute Cognate logic and integrate the returned Delta
                # Cognate.execute must ONLY return a delta, never the full state.
                result_delta = cognate.execute(current_state)
                state_provider.apply_delta(result_delta)

                # 4. Optional: Check for halt condition to prevent run-away loops during audit
                if current_state.get("halt"):
                    print("[SYSTEM] HALT SIGNAL DETECTED. OPENING CIRCUIT.")
                    break

                # v1.3.5: Temporary safety yield for async GUI compatibility
                import time
                time.sleep(0.1)
        finally:
            # Drop the active-store handle so a stale reference can't leak into
            # a later Cognate call made outside run_cycle. Phase G removed the
            # shim uninstall block that previously lived alongside this --
            # nothing module-level needs to be reversed under the cognate path.
            self._active_store = None
