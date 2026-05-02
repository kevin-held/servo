"""
Tests for core/config_registry.py — the cold-reload tunables store
introduced in Phase E (UPGRADE_PLAN_4 sec 4).

Run: pytest tests/test_config_registry.py -v

Coverage:
  - Defaults returned when config.json is absent.
  - Defaults returned when config.json is malformed (bad JSON, non-dict).
  - Overlay values override defaults when config.json is present.
  - Partial overlay preserves unaffected defaults.
  - Unknown keys return None (or caller-supplied default).
  - reload() re-reads after the file changes.
  - as_dict() returns a copy, not the live store.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config_registry import ConfigRegistry


class TestDefaultsOnMissingFile(unittest.TestCase):
    """A non-existent config.json must not raise; defaults apply."""

    def test_all_defaults_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"  # intentionally not created
            reg = ConfigRegistry(path=missing)
            self.assertEqual(reg.get("epsilon_0"), 0.3)
            self.assertEqual(reg.get("lambda_decay"), 0.001)
            self.assertEqual(reg.get("embed_dim"), 768)
            self.assertEqual(reg.get("commit_threshold"), 0.8)
            self.assertEqual(reg.get("nn_similarity_floor"), 0.7)
            self.assertEqual(reg.get("embed_model"), "nomic-embed-text")
            self.assertEqual(
                reg.get("observe_roots"), ["core", "gui", "tools", "codex"]
            )


class TestDefaultsOnMalformedFile(unittest.TestCase):
    """Malformed JSON or non-dict root must degrade silently to defaults."""

    def test_bad_json_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "config.json"
            bad.write_text("{not valid json", encoding="utf-8")
            reg = ConfigRegistry(path=bad)
            self.assertEqual(reg.get("epsilon_0"), 0.3)

    def test_non_dict_root_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "config.json"
            bad.write_text('["not", "a", "dict"]', encoding="utf-8")
            reg = ConfigRegistry(path=bad)
            self.assertEqual(reg.get("embed_dim"), 768)

    def test_empty_file_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "config.json"
            bad.write_text("", encoding="utf-8")
            reg = ConfigRegistry(path=bad)
            self.assertEqual(reg.get("embed_model"), "nomic-embed-text")


class TestOverlayOverridesDefault(unittest.TestCase):
    """When a key is in config.json, it wins over _DEFAULTS."""

    def test_single_key_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"epsilon_0": 0.5}), encoding="utf-8")
            reg = ConfigRegistry(path=path)
            self.assertEqual(reg.get("epsilon_0"), 0.5)
            # Non-overridden keys still return defaults.
            self.assertEqual(reg.get("lambda_decay"), 0.001)

    def test_multiple_keys_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({
                    "nn_similarity_floor": 0.65,
                    "embed_model": "mxbai-embed-large",
                }),
                encoding="utf-8",
            )
            reg = ConfigRegistry(path=path)
            self.assertEqual(reg.get("nn_similarity_floor"), 0.65)
            self.assertEqual(reg.get("embed_model"), "mxbai-embed-large")
            # Unaffected default still intact.
            self.assertEqual(reg.get("commit_threshold"), 0.8)


class TestUnknownKey(unittest.TestCase):
    """Keys not in _DEFAULTS and not in config.json return None (or caller default)."""

    def test_unknown_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"
            reg = ConfigRegistry(path=missing)
            self.assertIsNone(reg.get("nonexistent_key"))

    def test_caller_default_for_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"
            reg = ConfigRegistry(path=missing)
            self.assertEqual(reg.get("nonexistent_key", "fallback"), "fallback")

    def test_caller_default_does_not_override_registry_default(self):
        # A known key must return its _DEFAULTS value even if the caller
        # supplies a different default -- protects against typo-driven
        # fallback bypasses.
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"
            reg = ConfigRegistry(path=missing)
            self.assertEqual(reg.get("epsilon_0", 0.99), 0.3)


class TestReload(unittest.TestCase):
    """reload() re-reads config.json after the file changes on disk."""

    def test_reload_picks_up_new_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"epsilon_0": 0.5}), encoding="utf-8")
            reg = ConfigRegistry(path=path)
            self.assertEqual(reg.get("epsilon_0"), 0.5)

            # Mutate file on disk.
            path.write_text(json.dumps({"epsilon_0": 0.1}), encoding="utf-8")
            # Before reload, registry still has old value.
            self.assertEqual(reg.get("epsilon_0"), 0.5)

            reg.reload()
            self.assertEqual(reg.get("epsilon_0"), 0.1)

    def test_reload_with_removed_file_keeps_last_good(self):
        # Reload semantics are overlay, not replace. Removing the file
        # between reads keeps the last-good overlay, since the reload
        # exits early on missing path.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"epsilon_0": 0.5}), encoding="utf-8")
            reg = ConfigRegistry(path=path)
            self.assertEqual(reg.get("epsilon_0"), 0.5)

            path.unlink()
            reg.reload()
            # Last overlay value persists; file-missing is a no-op.
            self.assertEqual(reg.get("epsilon_0"), 0.5)


class TestAsDictIsCopy(unittest.TestCase):
    """as_dict() returns a shallow copy; mutating it must not affect the registry."""

    def test_mutation_does_not_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"
            reg = ConfigRegistry(path=missing)
            snap = reg.as_dict()
            snap["epsilon_0"] = 999.0
            self.assertEqual(reg.get("epsilon_0"), 0.3)

    def test_snapshot_contains_all_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"
            reg = ConfigRegistry(path=missing)
            snap = reg.as_dict()
            for key in ConfigRegistry._DEFAULTS:
                self.assertIn(key, snap)


class TestDefaultsClassLevelImmutable(unittest.TestCase):
    """The class-level _DEFAULTS dict must not be mutated by instance activity."""

    def test_overlay_does_not_mutate_class_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"epsilon_0": 0.99}), encoding="utf-8")
            _ = ConfigRegistry(path=path)
            # Class-level _DEFAULTS must still carry the Phase D literal.
            self.assertEqual(ConfigRegistry._DEFAULTS["epsilon_0"], 0.3)


if __name__ == "__main__":
    unittest.main()
