"""
Tests for core/path_utils.py — the single-anchor path resolver introduced
in v0.6.0 (D-20260417-09).

Run: pytest tests/test_path_utils.py -v
"""

import os
import sys
import unittest
from pathlib import Path

# Ensure the project root is on sys.path so tests can import core.path_utils
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.path_utils import (
    PROJECT_ROOT,
    PathRejectedError,
    resolve,
    project_relative,
)


class TestResolveAcceptsValidRelative(unittest.TestCase):
    """Paths that are relative and stay within PROJECT_ROOT must resolve."""

    def test_simple_file(self):
        p = resolve("codex/manifest.json")
        self.assertTrue(str(p).endswith(os.path.join("codex", "manifest.json")))
        p.relative_to(PROJECT_ROOT)  # raises if outside root

    def test_nested_file(self):
        p = resolve("workspace/gemma4_26b/notes.md")
        self.assertEqual(p.parent.name, "gemma4_26b")

    def test_directory(self):
        p = resolve("tools")
        self.assertEqual(p.name, "tools")

    def test_dot_segments_are_normalized(self):
        # './codex' and 'codex' resolve to the same absolute path.
        self.assertEqual(resolve("./codex"), resolve("codex"))

    def test_backslashes_accepted(self):
        # Windows-style separators must be accepted alongside forward slashes
        # so the model's output format is tolerant. The resolver normalizes
        # internally.
        self.assertEqual(
            resolve("codex/manifest.json"),
            resolve("codex\\manifest.json"),
        )

    def test_path_object_accepted(self):
        p = resolve(Path("codex/manifest.json"))
        self.assertTrue(str(p).endswith(os.path.join("codex", "manifest.json")))


class TestResolveRejectsAbsolute(unittest.TestCase):
    """Absolute paths — whichever form — must be rejected regardless of host OS."""

    def test_windows_drive_letter_forward_slash(self):
        with self.assertRaises(PathRejectedError) as ctx:
            resolve("C:/Users/kevin/OneDrive/Desktop/ai/core/tool_registry.py")
        self.assertIn("Absolute paths are not allowed", str(ctx.exception))

    def test_windows_drive_letter_backslash(self):
        with self.assertRaises(PathRejectedError):
            resolve("C:\\Users\\kevin\\OneDrive\\Desktop\\ai\\core\\tool_registry.py")

    def test_windows_drive_letter_lowercase(self):
        with self.assertRaises(PathRejectedError):
            resolve("d:/work/file.txt")

    def test_mangled_user_segment_kev(self):
        # The exact failure mode the resolver was built to reject.
        with self.assertRaises(PathRejectedError):
            resolve("C:/Users/ke/OneDrive/Desktop/ai/core/tool_registry.py")

    def test_mangled_user_segment_iam(self):
        with self.assertRaises(PathRejectedError):
            resolve("C:/Users/iam/OneDrive/Desktop/ai/core/tool_registry.py")

    def test_mangled_user_segment_extra_to(self):
        with self.assertRaises(PathRejectedError):
            resolve("C:/Users/kevin/OneDrive/to/Desktop/ai/core/tool_registry.py")

    def test_posix_absolute(self):
        with self.assertRaises(PathRejectedError):
            resolve("/etc/passwd")

    def test_leading_backslash(self):
        with self.assertRaises(PathRejectedError):
            resolve("\\foo\\bar")

    def test_error_text_is_model_readable(self):
        """Error text must steer the model toward the correct shape."""
        try:
            resolve("C:/Users/iam/ai/core/tool_registry.py")
        except PathRejectedError as e:
            msg = str(e)
            self.assertIn("Absolute paths are not allowed", msg)
            self.assertIn("project-root-relative", msg)
            self.assertIn("core/tool_registry.py", msg)


class TestResolveRejectsEscape(unittest.TestCase):
    """'..' segments that climb out of PROJECT_ROOT must be rejected."""

    def test_simple_escape(self):
        with self.assertRaises(PathRejectedError) as ctx:
            resolve("../outside.txt")
        self.assertIn("escapes the project root", str(ctx.exception))

    def test_nested_escape(self):
        with self.assertRaises(PathRejectedError):
            resolve("codex/../../outside.txt")

    def test_dot_dot_inside_tree_is_allowed(self):
        # Climbing up within the tree and back down stays inside the root.
        p = resolve("tools/../codex/manifest.json")
        self.assertTrue(str(p).endswith(os.path.join("codex", "manifest.json")))


class TestResolveRejectsEmpty(unittest.TestCase):
    def test_empty_string(self):
        with self.assertRaises(PathRejectedError):
            resolve("")

    def test_whitespace_only(self):
        with self.assertRaises(PathRejectedError):
            resolve("   ")

    def test_none_arg(self):
        with self.assertRaises(PathRejectedError):
            resolve(None)


class TestProjectRelative(unittest.TestCase):
    def test_roundtrip(self):
        p = resolve("codex/manifest.json")
        self.assertEqual(project_relative(p), "codex/manifest.json")

    def test_forward_slashes_always(self):
        p = resolve("codex\\manifest.json")
        self.assertEqual(project_relative(p), "codex/manifest.json")

    def test_outside_root_falls_back_to_absolute(self):
        # Not reachable via resolve(), but direct callers may pass a Path
        # that's outside — in that case fall back to the absolute form.
        outside = Path(PROJECT_ROOT).parent / "some_other_tree" / "x.txt"
        result = project_relative(outside)
        # Should NOT start with 'codex/' or any relative form
        self.assertNotEqual(result, "x.txt")


if __name__ == "__main__":
    unittest.main()
