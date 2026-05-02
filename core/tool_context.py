# tool_context.py
#
# Phase F (UPGRADE_PLAN_5 sec 5) -- tool-context contract.
#
# Phase E retired the sqlite3.connect monkey-patch and replaced the
# memory-tools' state.db routing with an explicit `conn_factory` kwarg
# (D-20260424-01). One shim survived: `lx_loop_shim` still rewrites
# `tools.system_config._get_loop_ref` and `tools.context_dump._get_loop_ref`
# at install time so those two tools can read `loop.state` / `loop.config` /
# `loop.telemetry` under Cognate dispatch. That's the last live monkey-patch
# in the dispatch path.
#
# Phase F generalizes Phase E's `conn_factory` pattern into a uniform
# tool-context kwarg the registry caller injects at dispatch time. Five
# tools (system_config, context_dump, memory_manager, memory_snapshot,
# task) accept an optional `tool_context: ToolContext | None = None`.
# When provided, tools read state/config/telemetry/conn_factory/ollama
# off the context object rather than reaching into module globals or
# patched `_get_loop_ref` callables. When None, the legacy fallback paths
# remain (Phase E `conn_factory`, Phase D `_get_loop_ref` shim) so a
# CoreLoop boot path or a standalone tool test doesn't regress.
#
# Design notes:
#   - Dataclass over plain dict so consumers get IDE completion and
#     mypy-friendly access. The fields mirror the surface `LxLoopAdapter`
#     exposes today (state, config, telemetry, ollama) plus the Phase E
#     conn_factory and a typed escape hatch (`legacy_loop_ref`) for any
#     tool that genuinely needs the original CoreLoop reference.
#   - Every field is optional. A tool that needs only `conn_factory`
#     constructs a context with everything else None; tests can build
#     a minimal context the same way. The dataclass default factory
#     makes `ToolContext()` valid.
#   - Field types are `Any` rather than concrete classes (lx_StateStore,
#     ConfigRegistry, OllamaClient). This avoids a circular-import
#     thicket -- the cognates and the state store both want to import
#     this module, and ConfigRegistry already has callers in lx_state.
#     `Any` is the honest type: tools accept whatever surface the caller
#     hands them and will fail loudly if a method they expect isn't
#     present.
#   - Phase G+ may tighten the types or add a Protocol surface once
#     the shim retirement has settled. For now, the contract is
#     structural: tools document the methods they read off each field.
#
# D-20260426 (Phase F section 5).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolContext:
    """Runtime context handed to a tool at dispatch time.

    Phase F (UPGRADE_PLAN_5 sec 5) introduces this as the uniform
    successor to Phase E's `conn_factory` kwarg and Phase D's
    `_get_loop_ref` monkey-patch. Tools that need runtime context
    (state, config, telemetry, a SQLite connection, an Ollama client,
    or a legacy CoreLoop reference) accept an optional
    `tool_context: ToolContext | None = None` and read fields off it
    rather than reaching into module globals.

    Fields:
        state            -- lx_StateStore (Phase F+) or CoreLoop.state (legacy).
                            Tools read get/set or domain-specific methods like
                            `add_conversation_turn`, `query_success_vectors`.
        config           -- ConfigRegistry (Phase F+) or CoreLoop.config dict
                            (legacy). Tools read `.get(key, default)`.
        telemetry        -- counters facade. Tools that surface metrics
                            (context_dump primarily) read attribute counters
                            like `truncations_total`. Phase E shim returned
                            an empty dict; Phase F may pass through the
                            ServoCoreThread's counters once those land.
        conn_factory     -- zero-arg callable returning a sqlite3.Connection.
                            Phase E pattern, kept for compatibility. Memory-
                            tools will prefer `tool_context.conn_factory`
                            over their explicit `conn_factory` kwarg when
                            both are absent on the caller.
        ollama           -- OllamaClient (or null-object). Tools that need
                            text generation or embedding (Phase F's chat
                            REASON path; future cognate primitives) call
                            `.generate(...)` or `.embed(...)` here.
        legacy_loop_ref  -- escape hatch holding the original CoreLoop
                            reference. Empty under the ServoCore path; the
                            CoreLoop boot path may populate it for tools
                            that genuinely need the loop object (rare).

    All fields default to None. `ToolContext()` is a valid no-op context
    that lets every tool fall through to its legacy path. This is the
    intended shape for unit tests of tool internals that don't exercise
    the runtime context surface.
    """

    state:           Optional[Any]      = None
    config:          Optional[Any]      = None
    telemetry:       Optional[Any]      = None
    conn_factory:    Optional[Callable] = None
    ollama:          Optional[Any]      = None
    legacy_loop_ref: Optional[Any]      = None

    def has_conn(self) -> bool:
        """Convenience: True iff a usable conn_factory is attached.

        Memory-tools use this to decide between the explicit conn_factory
        kwarg, the context-supplied factory, and the literal Phase D
        sqlite3.connect path. The check is a stable extension point --
        if Phase G+ adds connection pooling or async connections, the
        decision moves into this helper rather than spreading across
        five tool files.
        """
        return callable(self.conn_factory)

    def with_overrides(self, **kwargs: Any) -> "ToolContext":
        """Return a copy of this context with the given fields overridden.

        Phase F's lx_Act may build a per-cycle context once and override
        the `conn_factory` for memory-tool dispatches without rebuilding
        the whole object. Equivalent to `dataclasses.replace(ctx, ...)`
        but exposed as a method so call sites don't need the import.
        """
        merged = {
            "state":           self.state,
            "config":          self.config,
            "telemetry":       self.telemetry,
            "conn_factory":    self.conn_factory,
            "ollama":          self.ollama,
            "legacy_loop_ref": self.legacy_loop_ref,
        }
        merged.update(kwargs)
        return ToolContext(**merged)


__all__ = ["ToolContext"]
