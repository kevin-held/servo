# lx_loop_shim.py
#
# Phase D - loop-ref shim that lets the five TOOL_IS_SYSTEM tools
# (task, system_config, context_dump, memory_manager, memory_snapshot)
# dispatch under Cognate control without editing the tool files.
#
# The dispatch surface in Phase C excluded these tools (D-20260422-05)
# because each depended on either a live CoreLoop reference or direct
# sqlite3 writes into state/state.db (the loop.py-owned database).
# Phase D preserves the No-Write policy on loop.py and on the tool
# files themselves by introducing this shim: an installable adapter
# that intercepts sqlite3.connect() from within the tool modules and
# redirects legacy-path writes to a Cognate-owned database, plus a
# LxLoopAdapter that satisfies the `_get_loop_ref()` surface the two
# UI-facing sys-tools read from.
#
# Everything the shim does is reversible. `install()` captures the
# originals and returns a handle whose `uninstall()` restores them.
# The `installed()` context manager is the intended entry point from
# ServoCore.run_cycle() so scope is strictly one cycle.
#
# D-20260423 (Phase D section 4).

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional


# The tool modules we rewrite the sqlite3 binding on. Sequenced to match
# the five-tool expansion in UPGRADE_PLAN_3 section 2.
_SQLITE_TARGET_TOOLS = (
    "tools.task",
    "tools.memory_manager",
    "tools.memory_snapshot",
)

# The tool modules whose `_get_loop_ref` we swap for an adapter-returning
# callable. system_config's native resolver uses QApplication; under
# headless Cognate dispatch it returns None, which makes the tool short-
# circuit into an error. The adapter gives the tool something coherent
# to read against when the Cognate surface supplies it.
_LOOP_REF_TARGET_TOOLS = (
    "tools.system_config",
    "tools.context_dump",
)


def _legacy_state_db() -> str:
    root = Path(__file__).parent.parent.resolve()
    return str((root / "state" / "state.db").resolve())


def _is_legacy_state_db(candidate: str) -> bool:
    """True iff candidate resolves to the legacy state/state.db file."""
    try:
        c = str(Path(candidate).resolve()).lower()
        return c == _legacy_state_db().lower()
    except Exception:
        return False


class _Sqlite3Proxy:
    """Drop-in replacement for the sqlite3 module inside a sys-tool.

    Forwards every attribute to the real sqlite3 module except connect(),
    which redirects calls targeting state/state.db to a Cognate-owned
    path. All other paths (tests' tmpdirs, :memory:, unrelated DBs) pass
    through unchanged.
    """

    def __init__(self, real_sqlite3, redirect_path: str):
        object.__setattr__(self, "_real", real_sqlite3)
        object.__setattr__(self, "_redirect_path", redirect_path)

    def connect(self, database: Any = None, *args, **kwargs):
        """Route legacy-state-db calls to the Cognate-owned DB."""
        if isinstance(database, (str, bytes, os.PathLike)):
            path_str = os.fspath(database) if not isinstance(database, bytes) else database.decode()
            if _is_legacy_state_db(path_str):
                Path(self._redirect_path).parent.mkdir(parents=True, exist_ok=True)
                return self._real.connect(self._redirect_path, *args, **kwargs)
        return self._real.connect(database, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._real, name)


class LxLoopAdapter:
    """Adapter that presents the CoreLoop surface expected by sys-tools."""

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
        return None


class _StateFacade:
    def __init__(self, store):
        self._store = store

    def get(self, key, default=None):
        mirror = getattr(self._store, "_json_mirror", None) or {}
        return mirror.get(key, default)

    def set(self, key, value):
        if hasattr(self._store, "_set_mirror_value"):
            self._store._set_mirror_value(key, value)


class _ConfigFacade:
    def __init__(self, store):
        self._state = _StateFacade(store)

    def set(self, parameter, value, loop_ref=None):
        self._state.set(parameter, value)
        return f"Updated '{parameter}' to '{value}' (Cognate-scope)"

    def get(self, parameter, default=None):
        return self._state.get(parameter, default)


class _OllamaNullObject:
    model = "unknown"
    temperature = 0.0
    num_predict = 0
    num_ctx = 0


class ShimHandle:
    """Return value of install(). Holds the originals for reversal.

    Phase D addendum: the ToolRegistry loads each tool file via
    `importlib.util.spec_from_file_location` / `module_from_spec`, which
    produces a module that is NOT registered in sys.modules. Patching
    `sys.modules["tools.memory_manager"].sqlite3` therefore does NOT
    affect the registry's private copy. To catch those, the handle tracks
    a second set of patched modules (the registry-owned ones) and exposes
    `patch_registry(registry)` so lx_Act can hand the registry to the
    shim after loading. `install()` also wraps `ToolRegistry._load_file`
    so any later reload is automatically patched. Everything reversible.
    """

    _SQLITE_TOOL_BASENAMES: frozenset = frozenset(
        n.rsplit(".", 1)[-1] for n in _SQLITE_TARGET_TOOLS
    )
    _LOOP_REF_TOOL_BASENAMES: frozenset = frozenset(
        n.rsplit(".", 1)[-1] for n in _LOOP_REF_TARGET_TOOLS
    )

    def __init__(self):
        self._sqlite3_originals: dict = {}
        self._loop_ref_originals: dict = {}
        self._registry_patches: list = []
        self._registry_loader_original = None
        self._redirect_path: Optional[str] = None
        self._adapter: Optional[LxLoopAdapter] = None
        self._installed = False

    def _apply_to_module(self, module) -> None:
        """Apply sqlite3 + loop-ref patches to a registry-loaded tool module."""
        if self._redirect_path is None:
            return
        tool_name = getattr(module, "TOOL_NAME", None) or getattr(module, "__name__", "")
        basename = str(tool_name).rsplit(".", 1)[-1]

        if basename in self._SQLITE_TOOL_BASENAMES:
            real = getattr(module, "sqlite3", None)
            if real is not None and not isinstance(real, _Sqlite3Proxy):
                self._registry_patches.append((module, "sqlite3", real))
                setattr(module, "sqlite3", _Sqlite3Proxy(real, self._redirect_path))

        if basename in self._LOOP_REF_TOOL_BASENAMES and self._adapter is not None:
            real_ref = getattr(module, "_get_loop_ref", None)
            if real_ref is not None and getattr(real_ref, "_lx_shim_patched", False) is not True:
                adapter = self._adapter
                def _ref(adapter=adapter):
                    return adapter
                _ref._lx_shim_patched = True
                self._registry_patches.append((module, "_get_loop_ref", real_ref))
                setattr(module, "_get_loop_ref", _ref)

            real_tel = getattr(module, "_get_loop_telemetry", None)
            if real_tel is not None and getattr(real_tel, "_lx_shim_patched", False) is not True:
                def _tel():
                    return {}
                _tel._lx_shim_patched = True
                self._registry_patches.append((module, "_get_loop_telemetry", real_tel))
                setattr(module, "_get_loop_telemetry", _tel)

    def patch_registry(self, registry) -> None:
        """Patch every already-loaded tool in a ToolRegistry instance."""
        tools = getattr(registry, "_tools", None) or {}
        for entry in tools.values():
            mod = entry.get("module") if isinstance(entry, dict) else None
            if mod is not None:
                self._apply_to_module(mod)

    def uninstall(self) -> None:
        """Restore every patched binding. Safe to call twice."""
        if not self._installed:
            return
        import importlib
        for mod_name, real in self._sqlite3_originals.items():
            try:
                mod = importlib.import_module(mod_name)
                setattr(mod, "sqlite3", real)
            except Exception:
                pass
        for mod_name, real in self._loop_ref_originals.items():
            try:
                key = mod_name.replace("::telemetry", "")
                mod = importlib.import_module(key)
                if mod_name.endswith("::telemetry"):
                    setattr(mod, "_get_loop_telemetry", real)
                else:
                    setattr(mod, "_get_loop_ref", real)
            except Exception:
                pass
        for module, attr, real in reversed(self._registry_patches):
            try:
                setattr(module, attr, real)
            except Exception:
                pass
        if self._registry_loader_original is not None:
            try:
                from core.tool_registry import ToolRegistry
                ToolRegistry._load_file = self._registry_loader_original
            except Exception:
                pass
        # Restore the global sqlite3.connect if we swapped it.
        global_orig = getattr(self, "_global_connect_original", None)
        if global_orig is not None:
            try:
                sqlite3.connect = global_orig
            except Exception:
                pass
            self._global_connect_original = None
        self._sqlite3_originals.clear()
        self._loop_ref_originals.clear()
        self._registry_patches.clear()
        self._registry_loader_original = None
        self._redirect_path = None
        self._adapter = None
        self._installed = False


def install(
    servo_core,
    lx_store,
    *,
    redirect_db_path: Optional[str] = None,
) -> ShimHandle:
    """Install the Cognate-dispatch adapter for the five sys-tools."""
    import importlib

    handle = ShimHandle()

    if redirect_db_path is None:
        store_dir = None
        for candidate in ("db_path", "_db_path", "data_dir", "_data_dir"):
            v = getattr(lx_store, candidate, None)
            if v:
                store_dir = Path(str(v)).parent
                break
        if store_dir is None:
            store_dir = Path(_legacy_state_db()).parent.parent / "state" / "_lx"
        store_dir.mkdir(parents=True, exist_ok=True)
        redirect_db_path = str((store_dir / "lx_memory.db").resolve())

    for mod_name in _SQLITE_TARGET_TOOLS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        real = getattr(mod, "sqlite3", sqlite3)
        handle._sqlite3_originals[mod_name] = real
        setattr(mod, "sqlite3", _Sqlite3Proxy(real, redirect_db_path))

    adapter = LxLoopAdapter(servo_core, lx_store)
    for mod_name in _LOOP_REF_TARGET_TOOLS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        real = getattr(mod, "_get_loop_ref", None)
        if real is None:
            real_t = getattr(mod, "_get_loop_telemetry", None)
            if real_t is not None:
                handle._loop_ref_originals[mod_name + "::telemetry"] = real_t
                setattr(mod, "_get_loop_telemetry", lambda: {})
            continue
        handle._loop_ref_originals[mod_name] = real
        setattr(mod, "_get_loop_ref", lambda adapter=adapter: adapter)

    handle._redirect_path = redirect_db_path
    handle._adapter = adapter

    # Global sqlite3.connect interceptor. Some tools bind a private alias
    # (e.g. memory_snapshot does `import sqlite3 as _sq`). That alias
    # bypasses the per-module sqlite3 attribute patch. Replacing the
    # sqlite3.connect function itself (path-filtered so only legacy
    # state/state.db calls redirect) catches those paths too. All other
    # sqlite callers pass through unchanged.
    _real_connect = sqlite3.connect

    def _intercepted_connect(database=None, *args, **kwargs):
        if isinstance(database, (str, bytes, os.PathLike)):
            path_str = os.fspath(database) if not isinstance(database, bytes) else database.decode()
            if _is_legacy_state_db(path_str):
                Path(redirect_db_path).parent.mkdir(parents=True, exist_ok=True)
                return _real_connect(redirect_db_path, *args, **kwargs)
        return _real_connect(database, *args, **kwargs)

    handle._global_connect_original = _real_connect
    sqlite3.connect = _intercepted_connect

    # Wrap ToolRegistry._load_file so any tool loaded after install() gets
    # patched as part of load. This catches the spec_from_file_location-ed
    # modules that are NOT in sys.modules.
    try:
        from core.tool_registry import ToolRegistry as _TR
        original_load_file = _TR._load_file
        handle._registry_loader_original = original_load_file

        def _patched_load_file(self, path, _orig=original_load_file, _handle=handle):
            _orig(self, path)
            for entry in getattr(self, "_tools", {}).values():
                if isinstance(entry, dict) and str(entry.get("path", "")) == str(path):
                    mod = entry.get("module")
                    if mod is not None:
                        _handle._apply_to_module(mod)
                    break

        _TR._load_file = _patched_load_file
    except Exception:
        pass

    handle._installed = True
    return handle


@contextmanager
def installed(servo_core, lx_store, *, redirect_db_path=None):
    """Context manager form - the intended call site from run_cycle()."""
    handle = install(servo_core, lx_store, redirect_db_path=redirect_db_path)
    try:
        yield handle
    finally:
        handle.uninstall()
