import unittest
import os
from unittest.mock import MagicMock, patch
from core.config import ConfigRegistry

class TestConfigRegistry(unittest.TestCase):
    @patch("core.config.get_system_defaults")
    def setUp(self, mock_defaults):
        # Mock system defaults to ensure hermetic tests
        mock_defaults.return_value = {
            "defaults": {
                "temperature": 0.7,
                "summarize_contextualize": True,
                "history_compression_trigger": 5.0,
                "verbosity": "Normal",
                "max_tokens": 1024
            },
            "bounds": {
                "temperature": [0.0, 1.5],
                "history_compression_trigger": [3.0, 30.0]
            }
        }
        self.mock_state = MagicMock()
        self.mock_ollama = MagicMock()
        # Mock default return for state.get
        self.mock_state.get.side_effect = lambda k, default=None: default
        
        # Initialize with a dummy state store and ollama client
        self.registry = ConfigRegistry(self.mock_state, self.mock_ollama)

    def test_get_fallback_explicit(self):
        # Line 46: Trigger fallback branch when get called with None
        val = self.registry.get("verbosity") # key without explicit fallback arg
        self.assertEqual(val, "Normal")

    def test_get_fallthrough_to_default(self):
        # Ensure that if Env and State are missing, it hits Tier 3 (Defaults)
        val = self.registry.get("temperature", 0.7)
        self.assertEqual(val, 0.7)

    def test_get_tier1_env_override(self):
        # Tier 1: Environment Variables
        with patch.dict(os.environ, {"SERVO_TEMPERATURE": "1.2"}):
            val = self.registry.get("temperature", 0.7)
            self.assertEqual(val, 1.2)

    def test_get_tier2_state_override(self):
        # Tier 2: Persistent State Store
        self.mock_state.get.side_effect = lambda k, default=None: "0.5" if k == "temperature" else default
        val = self.registry.get("temperature", 0.7)
        self.assertEqual(val, 0.5)

    def test_set_valid_value(self):
        # Test a successful set operation
        resp = self.registry.set("temperature", 0.8)
        self.assertIn("✓ temperature calibrated to 0.8", resp)
        self.mock_state.set.assert_called_with("temperature", "0.8")

    def test_set_out_of_bounds_default(self):
        # Temperature default bounds are [0.0, 1.5]
        resp = self.registry.set("temperature", 2.0)
        self.assertIn("Error: temperature out of bounds", resp)
        self.mock_state.set.assert_not_called()

    def test_set_out_of_bounds_dynamic_override(self):
        # Override bounds in state: [0.0, 2.5]
        self.mock_state.get.side_effect = lambda k, default=None: "2.5" if k == "bound_max_temperature" else default
        
        # Now 2.0 should be valid
        resp = self.registry.set("temperature", 2.0)
        self.assertIn("✓ temperature calibrated to 2.0", resp)
        self.mock_state.set.assert_any_call("temperature", "2.0")

    def test_set_verbosity_enum_validation(self):
        resp = self.registry.set("verbosity", "InvalidLevel")
        self.assertIn("Error: verbosity must be one of", resp)
        
        resp = self.registry.set("verbosity", "Detailed")
        self.assertIn("✓ verbosity calibrated to Detailed", resp)

    def test_set_with_loop_live_injection(self):
        # Test standard kernel attribute
        class FakeLoop:
            def __init__(self):
                self.history_compression_trigger = 0
                self.config_changed = MagicMock()
                self.ollama = MagicMock()
        
        fake_loop = FakeLoop()
        
        # Test special routing for ollama temperature
        self.registry.set("temperature", 0.9, loop_ref=fake_loop)
        self.assertEqual(fake_loop.ollama.temperature, 0.9)

        # Test special routing for ollama max_tokens
        self.registry.set("max_tokens", 500, loop_ref=fake_loop)
        self.assertEqual(fake_loop.ollama.num_predict, 500)

        # Test standard kernel attribute
        self.registry.set("history_compression_trigger", 20.0, loop_ref=fake_loop)
        self.assertEqual(fake_loop.history_compression_trigger, 20.0)
        
        # Verify signal emission (line 131)
        fake_loop.config_changed.emit.assert_called()

    def test_cast_value_bool(self):
        # Test various boolean truthy strings
        self.assertTrue(self.registry._cast_value("summarize_contextualize", "true"))
        self.assertTrue(self.registry._cast_value("summarize_contextualize", "1"))
        self.assertFalse(self.registry._cast_value("summarize_contextualize", "false"))
        self.assertFalse(self.registry._cast_value("summarize_contextualize", "0"))
        
        # Test literal bool (line 106)
        self.assertTrue(self.registry._cast_value("summarize_contextualize", True))

    def test_set_exception_handling(self):
        # Force an exception during cast
        with patch.object(self.registry, "_cast_value", side_effect=ValueError("Boom")):
            resp = self.registry.set("temperature", "garbage")
            self.assertIn("Error calibrating temperature: Boom", resp)

if __name__ == "__main__":
    unittest.main()
