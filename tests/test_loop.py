import unittest
from core.loop import CoreLoop

class DummyState:
    pass

class DummyOllama:
    pass

class DummyTools:
    pass

class TestCoreLoop(unittest.TestCase):
    def setUp(self):
        self.loop = CoreLoop(DummyState(), DummyOllama(), DummyTools())

    def test_parse_tool_call_simple(self):
        # A standard parse call without think blocks.
        text = '```json\n{"tool": "filesystem", "args": {"operation": "list", "path": "."}}\n```'
        result = self.loop._parse_tool_call(text)
        self.assertEqual(result, {"tool": "filesystem", "args": {"operation": "list", "path": "."}})

    def test_parse_tool_call_with_think(self):
        # A deepseek reasoning response containing <think> tags.
        text = '<think>\nI should list the files in the directory.\n</think>\n```json\n{"tool": "filesystem", "args": {"operation": "list", "path": "."}}\n```'
        result = self.loop._parse_tool_call(text)
        self.assertEqual(result, {"tool": "filesystem", "args": {"operation": "list", "path": "."}})

    def test_parse_tool_call_fallback(self):
        # Model fails to output the markdown wrappers, instead just outputs pure JSON.
        text = '<think>\nI will use a tool.\n</think>\n{"tool": "filesystem", "args": {"operation": "read", "path": "requirements.txt"}}'
        result = self.loop._parse_tool_call(text)
        self.assertEqual(result, {"tool": "filesystem", "args": {"operation": "read", "path": "requirements.txt"}})

    def test_parse_tool_call_invalid(self):
        # Not a tool call.
        text = "Hello, how can I assist you today?"
        result = self.loop._parse_tool_call(text)
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
