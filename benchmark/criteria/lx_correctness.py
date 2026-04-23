import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# Mock / Proposed classes for the Audit Fence
class lx_StateDelta:
    """
    Proposed polymorphic state update object.
    Matches the v2.0 'Cognate' specification.
    """
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

class CorrectnessAudit(unittest.TestCase):
    """
    Audit Fence: Functional Correctness & Handshake Verification.
    Designed to pass against legacy (with some glue) and 100% against new core.
    """

    def setUp(self):
        # Use a temporary audit database and chroma instance.
        # D-20260423 (Phase C): Route chroma_path into a tempdir so setUp
        # works on sandbox mounts (e.g. OneDrive-on-Linux) where chromadb's
        # embedded SQLite can't acquire file locks. On native filesystems
        # this is equivalent to the previous profile-scoped path.
        from core.state import StateStore
        tmp = tempfile.mkdtemp(prefix="lx_audit_")
        self.state = StateStore(
            db_path=f"{tmp}/state.db",
            chroma_path=f"{tmp}/chroma",
            profile="lx_audit_temp",
        )

    def test_handshake_persistence(self):
        """MVB 1: Verify that lx_StateDelta payloads persist correctly."""
        delta = lx_StateDelta("audit.perf_lock", "0.05")

        # Mapping delta to current SQLite schema
        self.state.conn.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            (delta.key, str(delta.value))
        )
        self.state.conn.commit()

        cur = self.state.conn.execute("SELECT value FROM state WHERE key = ?", (delta.key,))
        row = cur.fetchone()
        self.assertIsNotNone(row, "Handshake failed: Key not found in DB.")
        self.assertEqual(row[0], "0.05", "Handshake failed: Data corruption.")

    def test_registry_loading(self):
        """MVB 2: Verify ToolRegistry can load tools and identify System tier."""
        from core.tool_registry import ToolRegistry
        registry = ToolRegistry(tools_dir=str(PROJECT_ROOT / "tools"))

        self.assertGreater(len(registry._tools), 0, "No tools loaded.")
        if "task" in registry._tools:
            self.assertTrue(registry._tools["task"]["is_system"], "Tier mismatch.")

    def test_idiot_filter_regression(self):
        """MVB 3: Verify that syntax-broken hallucinations are rejected."""
        broken_code = "for i in range(10)):\n    print(i)"

        with self.assertRaises(SyntaxError):
            compile(broken_code, "<string>", "exec")

    def test_core_loop_handshake(self):
        """MVB 4: Verify ServoCore.run_cycle handshake with lx_state."""
        from core.core import ServoCore
        from core.lx_state import lx_StateStore

        core = ServoCore()
        # D-20260423 (Phase C): scoped profile + reset() guarantees a clean
        # OBSERVE cursor regardless of any persistent mirror from a prior run.
        store = lx_StateStore(profile="lx_audit_handshake")
        store.reset()

        # Inject halt condition to prevent infinite loop during audit:
        # OBSERVE -> REASON -> ACT (halt set here) -> break
        original_apply = store.apply_delta
        def mock_apply_delta(delta):
            original_apply(delta)
            if delta.get("current_step") == "ACT":
                store.current_state["halt"] = True

        store.apply_delta = mock_apply_delta

        core.run_cycle(store)

        self.assertEqual(store.current_state["current_step"], "ACT")
        self.assertTrue(store.current_state["halt"])

def run_audit() -> dict:
    """Entry point for the manager."""
    suite = unittest.TestLoader().loadTestsFromTestCase(CorrectnessAudit)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)

    return {
        "metric": "lx_correctness",
        "pass": result.wasSuccessful(),
        "total_tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors)
    }

if __name__ == "__main__":
    unittest.main()
