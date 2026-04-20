import unittest
import os
import shutil
import tempfile
from pathlib import Path
from core.tool_registry import ToolRegistry

class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_truncation_boundary(self):
        # Create a dummy tool that returns exactly 18000 characters
        code = """
TOOL_NAME = "dummy_huge"
def execute(**kwargs):
    return "X" * 18000
"""
        self.registry.create_tool("dummy_huge", code)
        
        # Execute tool
        result = self.registry.execute("dummy_huge", {})
        
        # Original cap is 16000. So we expect the output to be exactly 16000 Xs + footer.
        self.assertTrue(len(result) > 16000)
        self.assertTrue(result.startswith("X" * 16000))
        self.assertIn("[OUTPUT TRUNCATED", result)

    def test_json_truncation_safety(self):
        # If a tool returns a massive JSON dict, verification that the wrapper 
        # still cuts safely. While the JSON itself gets broken, the ToolRegistry shouldn't crash.
        code = """
import json
TOOL_NAME = "dummy_json"
def execute(**kwargs):
    payload = {"status": "ok", "data": "Y" * 18000}
    return json.dumps(payload)
"""
        self.registry.create_tool("dummy_json", code)
        result = self.registry.execute("dummy_json", {})
        
        # The result safely sliced the string and appended the warning instead of breaking Python.
        self.assertIn("[OUTPUT TRUNCATED", result)

    def test_tool_exception_containment(self):
        # Test what happens when an unknown Python Exception fires mid-execute
        code = """
TOOL_NAME = "dummy_fail"
def execute(**kwargs):
    raise ValueError("System broke fundamentally!")
"""
        self.registry.create_tool("dummy_fail", code)
        result = self.registry.execute("dummy_fail", {})
        
        # It should NOT crash the app but return an Error string natively to the agent.
        self.assertTrue(result.startswith("Error in dummy_fail:"))
        self.assertIn("System broke fundamentally!", result)

    def test_missing_tool_execution(self):
        result = self.registry.execute("does_not_exist", {})
        self.assertEqual(result, "Error: tool 'does_not_exist' not found")

if __name__ == "__main__":
    unittest.main()
