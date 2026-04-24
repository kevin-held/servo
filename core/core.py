# core.py
from core.lx_cognates import lx_Observe, lx_Reason, lx_Act, lx_Integrate

class ServoCore:
    """The Main Execution Engine for the Servo Core Upgrade."""

    def __init__(self, ollama=None):
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

    def run_cycle(self, state_provider):
        """The Main Execution Loop."""
        # D-20260423 (Phase C): Stash the active store on self so Cognates can
        # reach procedural_wins / legacy config via self.core._active_store.
        # Scoped to the run_cycle lifetime -- cleared when the loop breaks so
        # a later cycle can't accidentally inherit a stale handle.
        self._active_store = state_provider
        print("[SYSTEM] CIRCUIT CLOSED. SERVO ACTIVE.")

        # Phase D (UPGRADE_PLAN_3 sec 4): install the loop-ref shim for the
        # five TOOL_IS_SYSTEM tools now folded into the dispatch surface.
        # The shim intercepts sqlite3 writes on state/state.db and routes
        # them to a Cognate-owned DB, and exposes a LxLoopAdapter as the
        # result of `_get_loop_ref()` inside system_config/context_dump.
        # Scope is strictly this run_cycle -- `uninstall()` fires in the
        # finally block so a subsequent loop.py boot finds its originals.
        try:
            from core import lx_loop_shim
            shim_handle = lx_loop_shim.install(self, state_provider)
            # Expose on self so Cognates (specifically lx_Act._get_registry)
            # can call shim_handle.patch_registry(reg) to catch the registry-
            # owned module instances that sys.modules-level patching misses.
            self._lx_shim_handle = shim_handle
        except Exception as e:
            # Shim install failing is non-fatal -- the Cognates can still
            # dispatch the Phase C six. The Phase D five will likely skip
            # or fail but won't corrupt state.
            print(f"[WARN] lx_loop_shim.install failed: {e}")
            shim_handle = None
            self._lx_shim_handle = None

        try:
            # v2.0: The stateless loop that processes the Sovereign Ledger
            while True:
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
            # Always reverse the shim. Ordering matters: restore sys-tool
            # bindings before dropping the active-store handle so any tail
            # calls still see the adapter.
            if shim_handle is not None:
                try:
                    shim_handle.uninstall()
                except Exception:
                    pass

            # Drop the active-store handle so a stale reference can't leak into
            # a later Cognate call made outside run_cycle.
            self._active_store = None
dle is not None:
                try:
                    shim_handle.uninstall()
                except Exception:
                    pass

            # Drop the active-store handle so a stale reference can't leak into
            # a later Cognate call made outside run_cycle.
            self._active_store = None
