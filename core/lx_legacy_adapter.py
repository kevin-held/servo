# lx_legacy_adapter.py
#
# Phase G (UPGRADE_PLAN_6 sec 1, D-20260427-01) -- this module hosts
# the `LxLoopAdapter` class that used to live in `core/lx_loop_shim.py`.
# The shim file was deleted along with `core/loop.py` when the No-Write
# invariant was lifted; the adapter survives because `lx_cognates.py`
# still constructs one as the `legacy_loop_ref` field of the per-
# dispatch ToolContext for `tools/system_config.py` and
# `tools/context_dump.py`. Those two tools were originally written
# against the legacy CoreLoop's surface (state.get/set, telemetry
# counters, ollama client) and have not yet been refactored to talk
# to the cognate runtime directly. Until they are, the adapter
# bridges the gap.
#
# What this file is NOT:
#   - The monkey-patch installer. The Phase F retirement of
#     `_get_loop_ref` swapping (D-20260426-01 step 7) means there is
#     no `install()` / `ShimHandle` here. Those mechanisms went
#     away with `lx_loop_shim.py`.
#   - A long-term home. Once `system_config` and `context_dump`
#     accept a `tool_context` kwarg natively (Phase H+), the adapter
#     can be deleted outright and this file with it.

from __future__ import annotations

from typing import Optional


class LxLoopAdapter:
    """Adapter that presents the CoreLoop surface expected by sys-tools.

    `system_config` and `context_dump` both call `_get_loop_ref()`
    which historically returned the live `CoreLoop` QThread instance.
    Under cognate dispatch there is no CoreLoop, so we hand them an
    object that walks like one for the handful of attributes they
    actually read: `.state.get/set`, `.config.get/set`, `.ollama`,
    plus a long tail of int counters that default to zero.
    """

    def __init__(self, servo_core, lx_store, ollama_client: Optional[object] = None):
        self._core = servo_core
        self._store = lx_store
        self._ollama = ollama_client or getattr(servo_core, "ollama", None)

    @property
    def state(self):
        return _StateFacade(self._store)

    @property
    def config(self):
        return _ConfigFacade(self._store)

    @property
    def telemetry(self) -> dict:
        return {}

    @property
    def ollama(self):
        return self._ollama or _OllamaNullObject()

    # CoreLoop knob defaults read by various sys-tools. Phase E pinned
    # these values to match a fresh CoreLoop boot so the GUI and the
    # cognate path share a baseline.
    conversation_history = 0
    chain_limit = 0
    autonomous_loop_limit = 0
    max_auto_continues = 2
    verbosity = "Normal"
    stream_enabled = True
    hardware_throttling_enabled = False
    hardware_throttle_threshold_enter = 90.0
    hardware_throttle_threshold_exit = 80.0
    truncations_total = 0
    followup_truncations_total = 0
    auto_continues_total = 0
    auto_continue_give_ups_total = 0
    hardware_throttle_total = 0
    user_interrupts_total = 0
    history_compressions_total = 0
    tool_result_compressions_total = 0
    default_conversation_history = 0
    context_history = ()

    def __getattr__(self, name: str):
        # Anything the sys-tools poke for that we don't define above
        # resolves to None rather than AttributeError. The legacy
        # CoreLoop surface had a long tail of optional attributes;
        # this keeps the adapter forgiving without enumerating them.
        return None


class _StateFacade:
    """Read/write facade that reads the per-profile JSON mirror on
    `lx_StateStore`. Sys-tools that call `state.get(...)` see the same
    keys cognate code reads via `store.current_state[...]`.
    """

    def __init__(self, store):
        self._store = store

    def get(self, key, default=None):
        mirror = getattr(self._store, "_json_mirror", None) or {}
        return mirror.get(key, default)

    def set(self, key, value):
        if hasattr(self._store, "_set_mirror_value"):
            self._store._set_mirror_value(key, value)


class _ConfigFacade:
    """Mimic of the CoreLoop's `config` surface. The legacy config
    object accepted `(parameter, value, loop_ref=None)` -- we ignore
    `loop_ref` and route the assignment through the state facade.
    """

    def __init__(self, store):
        self._state = _StateFacade(store)

    def set(self, parameter, value, loop_ref=None):
        self._state.set(parameter, value)
        return f"Updated '{parameter}' to '{value}' (Cognate-scope)"

    def get(self, parameter, default=None):
        return self._state.get(parameter, default)


class _OllamaNullObject:
    """Stand-in for `ollama_client.OllamaClient` when none has been
    wired into the core. The sys-tools that read these attributes do
    so for prompt-context display only -- zeroes are fine.
    """

    model = "unknown"
    temperature = 0.0
    num_predict = 0
    num_ctx = 0


__all__ = ["LxLoopAdapter"]
