import json
import unittest
from unittest.mock import MagicMock, patch

import tools.system_config as system_config

class TestSystemConfig(unittest.TestCase):
    def setUp(self):
        self.mock_loop = MagicMock()
        self.mock_state = MagicMock()
        self.mock_loop.state = self.mock_state
        self.mock_loop.ollama.model = "gemma:2b"
        self.mock_loop.ollama.temperature = 0.7
        self.mock_loop.ollama.num_predict = 1024
        self.mock_loop.conversation_history = 5
        self.mock_loop.chain_limit = 3
        self.mock_loop.autonomous_loop_limit = 0
        self.mock_loop.max_auto_continues = 2
        self.mock_loop.verbosity = "Normal"
        self.mock_loop.continuous_mode = False
        self.mock_loop.stream_enabled = False
        
        # Default state gets
        self.mock_state.get.side_effect = lambda k, default: default

    @patch("tools.system_config._get_loop_ref")
    def test_get_operation(self, mock_get_loop):
        mock_get_loop.return_value = self.mock_loop
        
        result_json = system_config.execute(operation="get")
        result = json.loads(result_json)
        
        self.assertEqual(result["temperature"], 0.7)
        self.assertEqual(result["summarize_contextualize"], "True")
        self.assertIn("_safety_bounds", result)
        self.assertEqual(result["_safety_bounds"]["temperature"], [0.0, 1.5])

    @patch("tools.system_config._get_loop_ref")
    def test_set_operation_numeric(self, mock_get_loop):
        mock_get_loop.return_value = self.mock_loop
        
        # Test valid set
        resp = system_config.execute(operation="set", parameter="conversation_history", value="10")
        self.assertIn("✓ conversation_history set to 10", resp)
        self.assertEqual(self.mock_loop.conversation_history, 10)
        
        # Test out of bounds
        resp = system_config.execute(operation="set", parameter="conversation_history", value="100")
        self.assertIn("Error: conversation_history must be between 3 and 30", resp)

    @patch("tools.system_config._get_loop_ref")
    def test_set_operation_boolean(self, mock_get_loop):
        mock_get_loop.return_value = self.mock_loop
        
        # Test loop attribute boolean
        resp = system_config.execute(operation="set", parameter="continuous_mode", value="True")
        self.assertTrue(self.mock_loop.continuous_mode)
        
        # Test state-backed boolean
        resp = system_config.execute(operation="set", parameter="summarize_contextualize", value="False")
        self.mock_state.set.assert_any_call("summarize_contextualize", "False")

    @patch("tools.system_config._get_loop_ref")
    def test_set_bound_operation(self, mock_get_loop):
        mock_get_loop.return_value = self.mock_loop
        
        # Expand bounds
        resp = system_config.execute(operation="set_bound", parameter="temperature", max_value="2.0")
        self.assertIn("✓ safety bounds for 'temperature' updated: max=2.0", resp)
        self.mock_state.set.assert_any_call("bound_max_temperature", "2.0")
        
        # Verify that _get_bounds now returns the new max
        self.mock_state.get.side_effect = lambda k, default: "2.0" if k == "bound_max_temperature" else default
        
        # Test setting value with new expanded bound
        resp = system_config.execute(operation="set", parameter="temperature", value="1.8")
        self.assertIn("✓ temperature set to 1.8", resp)
        self.assertEqual(self.mock_loop.ollama.temperature, 1.8)

if __name__ == "__main__":
    unittest.main()
