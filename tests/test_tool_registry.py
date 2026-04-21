import unittest
import os
import shutil
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from core.tool_registry import ToolRegistry

class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        # Create a temp directory for tools
        self.test_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(tools_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_skips_underscore_files(self):
        # Create a file starting with _
        path = Path(self.test_dir) / "_hidden_tool.py"
        path.write_text("TOOL_NAME = 'hidden'", encoding="utf-8")
        
        self.registry.load_all()
        self.assertNotIn("hidden", self.registry.get_all_tools())

    def test_load_error_handling(self):
        # Create a corrupted python file (syntax error)
        path = Path(self.test_dir) / "broken_tool.py"
        path.write_text("This is not valid python code!!!", encoding="utf-8")
        
        # This should hit the except block in _load_file (line 51)
        with patch("core.tool_registry.get_logger") as mock_get_logger:
            self.registry._load_file(path)
            mock_get_logger.return_value.log.assert_called_with("ERROR", "tool_registry", "Failed to load broken_tool.py", unittest.mock.ANY)

    def test_get_tool_descriptions(self):
        # Create a valid tool
        path = Path(self.test_dir) / "valid_tool.py"
        path.write_text("TOOL_NAME='valid'\nTOOL_DESCRIPTION='desc'\nTOOL_SCHEMA={}\ndef execute(**kwargs): return 'ok'", encoding="utf-8")
        
        self.registry.load_all()
        desc = self.registry.get_tool_descriptions()
        self.assertEqual(len(desc), 1)
        self.assertEqual(desc[0]["name"], "valid")

    def test_get_tool_code_missing(self):
        # Line 74: tool not found
        code = self.registry.get_tool_code("non_existent")
        self.assertEqual(code, "")

    def test_execute_disabled_tool(self):
        # Create and disable a tool
        path = Path(self.test_dir) / "disabled_tool.py"
        path.write_text("TOOL_NAME='disabled'\nTOOL_ENABLED=False\ndef execute(**kwargs): return 'fail'", encoding="utf-8")
        
        self.registry.load_all()
        resp = self.registry.execute("disabled", {})
        self.assertIn("Error: tool 'disabled' is disabled", resp)

    def test_execute_not_found(self):
        # Line 85: tool not found
        resp = self.registry.execute("not_found", {})
        self.assertIn("Error: tool 'not_found' not found", resp)

    def test_execute_exception_handling(self):
        # Create a tool that fails at runtime (simulating dummy_fail log)
        path = Path(self.test_dir) / "dummy_fail.py"
        path.write_text("TOOL_NAME='dummy_fail'\ndef execute(**kwargs): raise RuntimeError('System broke fundamentally!')", encoding="utf-8")
        
        self.registry.load_all()
        resp = self.registry.execute("dummy_fail", {})
        self.assertIn("Error in dummy_fail: System broke fundamentally!", resp)

    def test_execute_output_truncation(self):
        # Create a tool that returns a lot of text
        path = Path(self.test_dir) / "big_tool.py"
        path.write_text("TOOL_NAME='big_tool'\ndef execute(**kwargs): return 'X' * 20000", encoding="utf-8")
        
        self.registry.load_all()
        # v1.2.1: Inject a mock config to test truncation via the new registry-first protocol
        mock_config = MagicMock()
        mock_config.get.return_value = 100
        self.registry.config = mock_config
        
        resp = self.registry.execute("big_tool", {})
        self.assertEqual(len(resp), 100 + len("\n\n[OUTPUT TRUNCATED — 20000 total chars, showing first 100. Use 'filesystem' read with a specific path for full content.]"))
        self.assertIn("OUTPUT TRUNCATED", resp)

    def test_mutations(self):
        # Create a tool
        path = Path(self.test_dir) / "mutant.py"
        path.write_text("TOOL_NAME='mutant'\nTOOL_ENABLED=True\ndef execute(**kwargs): return 'ok'", encoding="utf-8")
        self.registry.load_all()
        
        # Test set_enabled
        self.registry.set_enabled("mutant", False)
        self.assertFalse(self.registry._tools["mutant"]["enabled"])
        
        # Test save_tool_code
        new_code = "TOOL_NAME='mutant'\ndef execute(**kwargs): return 'new'"
        self.registry.save_tool_code("mutant", new_code)
        self.assertEqual(self.registry.get_tool_code("mutant"), new_code)
        
        # Test save_tool_code missing (Line 119)
        self.registry.save_tool_code("missing", "code")

    def test_create_tool(self):
        """Line 124-127: Verify create_tool method."""
        self.registry.create_tool("new_tool", "TOOL_NAME='new'\ndef execute(**kwargs): return 'ok'")
        self.assertIn("new", self.registry.get_all_tools())

if __name__ == "__main__":
    unittest.main()
