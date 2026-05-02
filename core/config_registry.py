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
    registry at __init__ and passes references. The dict is not mutated
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
        # Looser than nn_similarity_floor by design: env_snapshots index
        # the env_audit fingerprint rather than the prose observation
        # signature, so semantic matches are coarser by construction.
        # 0.6 keeps cold-start lookups productive without admitting the
        # 'everything is similar' regime that lower floors invite under
        # cosine distance on high-dim sparse vectors.
        "env_snapshot_similarity_floor": 0.6,
        # OllamaClient embed model (was a literal __init__ default).
        # Swapping this at runtime requires the procedural_wins collection
        # to be empty or to share the new dim with the old -- see the
        # _EMBED_DIM comment in lx_state.py for migration discipline.
        "embed_model":         "nomic-embed-text",
        # lx_Observe root set (was _OBSERVE_ROOTS on the class). Stored as
        # a list in JSON; callers that want a tuple should convert on read.
        "observe_roots":       ["core", "gui", "tools", "codex"],
    }

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
        # _last_reload_count is a simple counter incremented on every
        # successful reload; tests assert against it to confirm a
        # reload actually fired without depending on mtime granularity.
        self._last_mtime_ns: Optional[int] = None
        self._last_reload_count: int = 0
        self.reload()

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
                # Update in place; keys not in overlay keep their value.
                for key, value in overlay.items():
                    self._values[key] = value
                # Successful overlay -- bump counter for tests/telemetry
                # and refresh the mtime cache so the next maybe_reload
                # has a current baseline. We refresh inside the success
                # branch so a malformed file doesn't poison the cache.
                self._last_reload_count += 1
                try:
                    self._last_mtime_ns = self._path.stat().st_mtime_ns
                except OSError:
                    # Defensive: a race where the file is unlinked between
                    # read and stat. Leave _last_mtime_ns at its prior
                    # value so the next maybe_reload re-detects.
                    pass
        except Exception:
            # Never raise on bad config. A broken config.json is a
            # deployment accident, not a loop-stopping condition. The
            # registry falls back to whatever state it was in before
            # (defaults on first call; last-good on subsequent calls).
            return

    def maybe_reload(self) -> bool:
        """Re-read config.json iff its mtime changed since the last
        successful reload.

        Phase F (UPGRADE_PLAN_5 sec 8) -- the cognate loop calls this at
        the top of every cycle so a config edit lands within one cycle
        of save without restarting the engine. The check is one stat()
        call per cycle, which is cheap relative to env_audit's tree
        walk.

        Returns True if a reload fired (mtime changed and file was
        readable), False otherwise (file missing, mtime unchanged, or
        stat failed). Callers do not need to inspect the return; it
        exists for telemetry and for a future watchdog that wants to
        log config changes.
        """
        try:
            if not self._path.exists():
                return False
            current_mtime = self._path.stat().st_mtime_ns
        except OSError:
            return False
        if self._last_mtime_ns is not None and current_mtime == self._last_mtime_ns:
            return False
        # mtime changed (or first observation). Delegate to reload(),
        # which handles the JSON parse + cache update. We compare the
        # reload counter before and after to confirm whether the
        # reload actually applied -- a mtime bump on a file that turns
        # out to be malformed JSON should leave the registry alone but
        # still update _last_mtime_ns so we don't retry every cycle.
        prior_count = self._last_reload_count
        self.reload()
        if self._last_reload_count == prior_count:
            # The overlay parse failed. Update _last_mtime_ns so we
            # don't loop on the same broken file every cycle. The
            # registry retains its last-good values.
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

        The caller-supplied default takes precedence over None but never
        over _DEFAULTS, so a typo in the config.json key doesn't silently
        override a known default with the caller's fallback. If you want
        caller-default to win over registry-default, either add the key to
        _DEFAULTS first or use `get_raw` (absent -- intentionally, to
        discourage the pattern).
        """
        if key in self._values:
            return self._values[key]
        if key in self._DEFAULTS:
            return self._DEFAULTS[key]
        return default

    def as_dict(self) -> dict:
        """Return a shallow copy of the current overlay state.

        Useful for telemetry snapshots (Phase F) and for ADR audit trails
        when a config change affects a landing. The dict is a copy, so
        mutating the return value does not affect the registry.
        """
        return dict(self._values)

    def __repr__(self) -> str:
        return f"ConfigRegistry(path={self._path}, keys={sorted(self._values.keys())})"
