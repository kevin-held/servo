# config_registry.py
#
# Phase E (UPGRADE_PLAN_4 sec 4) -- cold-reload tunables store.
#
# Phase C and D deliberately deferred configuration migration. Six
# hardcoded literals drove the reasoning layer (epsilon-greedy schedule,
# embedding dimensionality, commit threshold, NN similarity floor, embed
# model, observe roots) with a comment in each call site promising Phase E
# would move them to a registry. This module is that registry.
#
# Design notes:
#   - Cold-reload only on first pass. Phase F adds mtime-driven hot reload.
#     Phase E's ConfigRegistry() reads config.json once at instantiation;
#     reload() re-reads on demand.
#   - Missing keys fall back to code-level _DEFAULTS so a deleted or absent
#     config.json is never a regression -- it is equivalent to running
#     Phase D literals.
#   - A malformed config.json (bad JSON, non-dict root) degrades silently
#     to defaults rather than raising. Config is infrastructure; a bad
#     config file must never open the circuit.
#   - _DEFAULTS is the single source of truth. Any call site asking for a
#     key not in _DEFAULTS gets None (or the caller-supplied default),
#     which matches dict.get semantics and lets downstream code make its
#     own fallback decision.
#
# D-20260424.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from core.identity import get_system_defaults

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class ConfigRegistry:
    """Cold-reload tunables store backed by codex/manifests/config.json.

    Phase E scope (UPGRADE_PLAN_4 sec 4): migrate seven Phase D literals
    into a single authoritative registry, without committing to an
    over-engineered config system. Phase F will add hot reload and
    telemetry-driven tuning on top of this surface.

    Usage:
        cfg = ConfigRegistry()                  # reads codex/manifests/config.json
        eps = cfg.get("epsilon_0")              # 0.3 if unset
        sim = cfg.get("nn_similarity_floor", 0.5)  # caller default overrides _DEFAULTS

    Thread-safety: single-threaded by design. ServoCore instantiates one
    registry and passes references. The dict is not mutated
    after reload(); callers read values rather than holding references to
    the underlying store.
    """

    # _DEFAULTS mirrors the Phase D literals exactly so a missing
    # config.json is a no-op regression. Every call site migrating from a
    # literal MUST check this dict for its key; the literal is the fallback
    # when config is None (legacy boot path).
    _DEFAULTS: dict = {
        # lx_Reason epsilon-greedy schedule (was _EPSILON_0, _LAMBDA in
        # lx_cognates.py). Phase D kept these at module scope with a
        # comment flagging Phase E migration.
        "epsilon_0":           0.3,
        "lambda_decay":        0.001,
        # lx_StateStore embedding + commit parameters (was _EMBED_DIM at
        # module scope and _COMMIT_THRESHOLD on the class in lx_state.py).
        "embed_dim":           768,
        "commit_threshold":    0.8,
        # lx_StateStore.query_success_vectors similarity floor (was a
        # parameter default on the method in lx_state.py).
        "nn_similarity_floor": 0.7,
        # Phase G (UPGRADE_PLAN_6 sec 3f) -- env_snapshots similarity floor.
        "env_snapshot_similarity_floor": 0.6,
        # OllamaClient embed model (was a literal __init__ default).
        "embed_model":         "nomic-embed-text",
        # lx_Observe root set (was _OBSERVE_ROOTS on the class).
        "observe_roots":       ["core", "gui", "tools", "codex"],
    }

    # Type map for casting values written via set()
    _TYPE_MAP: dict = {
        "temperature": float,
        "max_tokens": int,
        "conversation_history": int,
        "chain_limit": int,
        "autonomous_loop_limit": int,
        "max_auto_continues": int,
        "history_compression_trigger": float,
        "history_compression_target_chars": int,
        "tool_result_compression_threshold": int,
        "tool_result_compression_target_chars": int,
        "hardware_throttle_threshold_enter": float,
        "hardware_throttle_threshold_exit": float,
        "stream_enabled": bool,
        "hardware_throttling_enabled": bool,
        "summarize_contextualize": bool,
        "summarize_history_integrate": bool,
        "summarize_tool_results": bool,
        "summarize_read_enabled": bool,
        "summarize_read_threshold": int,
        "verbosity": str,
    }

    _VERBOSITY_OPTIONS = {"Concise", "Normal", "Standard", "Detailed"}

    def __init__(self, path: Optional[Path] = None):
        """Read config.json once. Defaults are installed first so a failed
        read still leaves the registry in a usable state.
        """
        self._path: Path = Path(path) if path is not None else (
            _PROJECT_ROOT / "codex" / "manifests" / "config.json"
        )
        # Copy _DEFAULTS rather than aliasing so the class-level dict is
        # never mutated by reload() overlays.
        self._values: dict = dict(self._DEFAULTS)
        # Phase F (UPGRADE_PLAN_5 sec 8) -- track the last seen mtime so
        # `maybe_reload()` can decide cheaply whether the file has
        # changed since the previous reload. None signals "never seen".
        self._last_mtime_ns: Optional[int] = None
        self._last_reload_count: int = 0
        self.reload()

        # Optional references wired post-construction so set() can
        # persist values and live-inject into the loop.
        self._state = None
        self._loop_ref = None

        # Bounds from system_defaults.json
        self._bounds = get_system_defaults().get("bounds", {})

    # ------------------------------------------------------------------
    # Binding helpers -- wired by ServoCoreThread after construction.
    # ------------------------------------------------------------------

    def bind_state(self, state) -> None:
        """Wire a StateStore for set() persistence."""
        self._state = state

    def bind_loop(self, loop) -> None:
        """Wire a loop reference for live memory injection."""
        self._loop_ref = loop

    def reload(self) -> None:
        """Re-read config.json. Silently degrades to defaults on any
        error -- missing file, malformed JSON, non-dict root.

        Reload semantics: overlay, not replace. Keys absent from the new
        config file retain their prior value (which may itself be a
        default). Phase F's hot-reload path calls this via
        `maybe_reload()`; explicit callers can still invoke it
        directly for unconditional re-reads (e.g. after a deliberate
        config write from inside a tool).
        """
        try:
            if not self._path.exists():
                return
            raw = self._path.read_text(encoding="utf-8")
            overlay = json.loads(raw)
            if isinstance(overlay, dict):
                for key, value in overlay.items():
                    self._values[key] = value
                self._last_reload_count += 1
                try:
                    self._last_mtime_ns = self._path.stat().st_mtime_ns
                except OSError:
                    pass
        except Exception:
            return

    def maybe_reload(self) -> bool:
        """Re-read config.json iff its mtime changed since the last
        successful reload.

        Returns True if a reload fired (mtime changed and file was
        readable), False otherwise.
        """
        try:
            if not self._path.exists():
                return False
            current_mtime = self._path.stat().st_mtime_ns
        except OSError:
            return False
        if self._last_mtime_ns is not None and current_mtime == self._last_mtime_ns:
            return False
        prior_count = self._last_reload_count
        self.reload()
        if self._last_reload_count == prior_count:
            self._last_mtime_ns = current_mtime
            return False
        return True

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for `key`.

        Lookup order:
          1. Overlay from config.json (if loaded and key present)
          2. _DEFAULTS (if key present)
          3. Caller-supplied `default` argument
          4. None
        """
        if key in self._values:
            return self._values[key]
        if key in self._DEFAULTS:
            return self._DEFAULTS[key]
        return default

    # ------------------------------------------------------------------
    # set() -- validates, persists, and live-injects a config value.
    # Compatible with the contract system_config.py expects.
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any, loop_ref=None) -> str:
        """Validate and persist a configuration change.

        Parameters
        ----------
        key : str
            The parameter name.
        value : Any
            The new value (will be cast to the expected type).
        loop_ref : optional
            A loop reference for live memory injection. Falls back to
            the bound loop if not provided.
        """
        try:
            val = self._cast_value(key, value)

            # Bounds check
            if key in self._bounds:
                bounds_pair = self._bounds[key]
                if isinstance(bounds_pair, list) and len(bounds_pair) == 2:
                    lo, hi = float(bounds_pair[0]), float(bounds_pair[1])
                    # Allow dynamic overrides from state
                    if self._state is not None:
                        try:
                            lo = float(self._state.get(f"bound_min_{key}", str(lo)))
                            hi = float(self._state.get(f"bound_max_{key}", str(hi)))
                        except (TypeError, ValueError):
                            pass
                    if isinstance(val, (int, float)) and not (lo <= val <= hi):
                        return f"Error: {key} out of bounds ({lo}-{hi}). Received {val}."

            # Enum validation
            if key == "verbosity" and val not in self._VERBOSITY_OPTIONS:
                return f"Error: verbosity must be one of {self._VERBOSITY_OPTIONS}."

            # Persist to state store
            if self._state is not None:
                try:
                    self._state.set(key, str(val))
                except Exception:
                    pass

            # Update in-memory overlay so subsequent get() calls see it
            self._values[key] = val

            # Live injection into the loop
            ref = loop_ref or self._loop_ref
            if ref is not None:
                self._apply_to_memory(ref, key, val)

            return f"✓ {key} calibrated to {val}"
        except Exception as e:
            return f"Error calibrating {key}: {e}"

    def _cast_value(self, key: str, value: Any) -> Any:
        """Coerce a value to the expected type for `key`."""
        if value is None:
            return None
        target = self._TYPE_MAP.get(key)
        if target is None:
            return value
        if target == bool:
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes", "on")
        if target == float:
            return float(value)
        if target == int:
            return int(float(value))
        return str(value)

    def _apply_to_memory(self, loop, key: str, value: Any) -> None:
        """Route a validated value to the correct in-memory attribute."""
        ollama = getattr(loop, "ollama", None)
        if key == "temperature" and ollama is not None:
            ollama.temperature = value
        elif key == "max_tokens" and ollama is not None:
            ollama.num_predict = value
        elif hasattr(loop, key):
            setattr(loop, key, value)

        # Emit signal for GUI sync
        if hasattr(loop, "config_changed"):
            try:
                loop.config_changed.emit(key, value)
            except Exception:
                pass

    def as_dict(self) -> dict:
        """Return a shallow copy of the current overlay state.

        Useful for telemetry snapshots (Phase F) and for ADR audit trails
        when a config change affects a landing. The dict is a copy, so
        mutating the return value does not affect the registry.
        """
        return dict(self._values)

    def __repr__(self) -> str:
        return f"ConfigRegistry(path={self._path}, keys={sorted(self._values.keys())})"
