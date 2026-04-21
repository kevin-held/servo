import unittest
import os
import json
import shutil
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import tools.system_config as system_config

class TestSystemConfigTool(unittest.TestCase):
    def setUp(self):
        # Create a temp directory for configs to avoid eating root 'configs/'
        self.tmp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmp_dir) / "configs"
        self.config_dir.mkdir(exist_ok=True)
        
        # We need to mock the UI environment for _get_loop_ref() to work (or fail predictably)
        self.mock_loop = MagicMock()
        self.mock_loop.ollama.model = "test-model"
        self.mock_loop.ollama.temperature = 0.7
        self.mock_loop.ollama.num_predict = 4096
        self.mock_loop.conversation_history = 20
        self.mock_loop.chain_limit = 10
        self.mock_loop.autonomous_loop_limit = 5
        self.mock_loop.max_auto_continues = 3
        self.mock_loop.verbosity = "Normal"
        self.mock_loop.stream_enabled = True
        self.mock_loop.hardware_throttling_enabled = False
        self.mock_loop.hardware_throttle_threshold_enter = 90.0
        self.mock_loop.hardware_throttle_threshold_exit = 80.0
        
        # Mock state
        self.mock_loop.state.get.side_effect = lambda k, default: default

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("tools.system_config._get_loop_ref")
    def test_get_operation(self, mock_get_loop):
        mock_get_loop.return_value = self.mock_loop
        
        # Test full GET
        resp = system_config.execute(operation="get")
        data = json.loads(resp)
        self.assertEqual(data["model"], "test-model")
        self.assertEqual(data["temperature"], 0.7)
        self.assertIn("_safety_bounds", data)
        
        # Test single parameter GET (Line 151)
        resp_single = system_config.execute(operation="get", parameter="temperature")
        data_single = json.loads(resp_single)
        self.assertEqual(data_single["temperature"], 0.7)

    @patch("tools.system_config._get_loop_ref")
    def test_set_operation(self, mock_get_loop):
        mock_get_loop.return_value = self.mock_loop
        self.mock_loop.config.set.return_value = "✓ temperature set to 0.5"
        
        resp = system_config.execute(operation="set", parameter="temperature", value="0.5")
        self.assertIn("temperature set to 0.5", resp)
        self.mock_loop.config.set.assert_called_with("temperature", "0.5", loop_ref=self.mock_loop)

    @patch("tools.system_config._get_loop_ref")
    def test_set_bound_operation(self, mock_get_loop):
        mock_get_loop.return_value = self.mock_loop
        
        # Line 159: parameter required
        resp_err = system_config.execute(operation="set_bound")
        self.assertIn("Error: 'parameter' is required", resp_err)
        
        # Line 160: unsupported parameter
        resp_err2 = system_config.execute(operation="set_bound", parameter="invalid")
        self.assertIn("Error: Bounds not supported", resp_err2)
        
        # Valid set_bound
        resp = system_config.execute(operation="set_bound", parameter="temperature", min_value="0.1", max_value="0.9")
        self.assertIn("safety bounds for 'temperature' updated", resp)
        self.mock_loop.state.set.assert_any_call("bound_min_temperature", "0.1")
        self.mock_loop.state.set.assert_any_call("bound_max_temperature", "0.9")
        self.mock_loop.config_changed.emit.assert_called()

    @patch("tools.system_config.Path")
    @patch("tools.system_config._get_loop_ref")
    def test_save_load_operations(self, mock_get_loop, mock_path):
        mock_get_loop.return_value = self.mock_loop
        self.mock_loop.config.set.return_value = "OK"
        
        # Configure mock_path so that Path("configs") returns our tmp config_dir
        def side_effect(arg1, *args):
            from pathlib import Path as GenuinePath
            if str(arg1) == "configs":
                return self.config_dir
            return GenuinePath(arg1, *args)
        mock_path.side_effect = side_effect
        
        # SAVE
        resp_save = system_config.execute(operation="save", value="test_config.json")
        self.assertIn("✓ Configuration saved", resp_save)
        
        # LOAD
        self.mock_loop.ollama.model = "old"
        resp_load = system_config.execute(operation="load", value="test_config.json")
        self.assertIn("✓ Configuration loaded", resp_load)
        self.assertEqual(self.mock_loop.ollama.model, "test-model")
        
        # LOAD Error (Line 212-213)
        with patch("json.load", side_effect=json.JSONDecodeError("msg", "doc", 0)):
             resp_err = system_config.execute(operation="load", value="test_config.json")
             self.assertIn("Error loading config", resp_err)

    @patch("tools.system_config.Path")
    @patch("tools.system_config._get_loop_ref")
    def test_edge_cases(self, mock_get_loop, mock_path):
        mock_get_loop.return_value = self.mock_loop
        
        # Configure mock_path same way
        def side_effect(arg1, *args):
            from pathlib import Path as GenuinePath
            if str(arg1) == "configs":
                return self.config_dir
            return GenuinePath(arg1, *args)
        mock_path.side_effect = side_effect

        # SAVE Error (Line 187-188)
        with patch("builtins.open", side_effect=IOError("Write failed")):
            resp_err = system_config.execute(operation="save", value="fail.json")
            self.assertIn("Error saving config: Write failed", resp_err)

        # Error: CoreLoop does not have a config registry (Line 114)
        del self.mock_loop.config
        resp_no_reg = system_config.execute(operation="set", parameter="temp", value="0.5")
        self.assertIn("Error: CoreLoop does not have a config registry", resp_no_reg)
        self.mock_loop.config = MagicMock() # restore
        
        # _get_bounds conversion error (Line 107-108)
        self.mock_loop.state.get.side_effect = None
        self.mock_loop.state.get.return_value = "invalid-float"
        b = system_config._get_bounds(self.mock_loop, "temperature")
        self.assertEqual(b, (0.0, 1.5))
        
        # Unknown operation (Line 215)
        resp = system_config.execute(operation="magic")
        self.assertIn("Error: Unknown operation", resp)

    def test_get_loop_ref_exception(self):
        """Line 95 coverage."""
        with patch("PySide6.QtWidgets.QApplication") as mock_qapp:
            mock_app = MagicMock()
            mock_qapp.instance.return_value = mock_app
            mock_app.topLevelWidgets.side_effect = RuntimeError("Crash")
            self.assertIsNone(system_config._get_loop_ref())

    def test_no_loop_error(self):
        # Line 123: Loop is None
        with patch("tools.system_config._get_loop_ref", return_value=None):
            resp = system_config.execute()
            self.assertIn("Error: Could not access the running CoreLoop instance", resp)

    def test_get_loop_ref_ui_mock(self):
        """Covers lines 87-96 by mocking QApplication and widgets."""
        with patch("PySide6.QtWidgets.QApplication") as mock_qapp:
            # 1. App is None
            mock_qapp.instance.return_value = None
            self.assertIsNone(system_config._get_loop_ref())
            
            # 2. App exists, but no widgets have .loop
            mock_app = MagicMock()
            mock_qapp.instance.return_value = mock_app
            mock_widget = MagicMock(spec=[]) # No 'loop' attr
            mock_app.topLevelWidgets.return_value = [mock_widget]
            self.assertIsNone(system_config._get_loop_ref())
            
            # 3. Widget has loop
            mock_widget_with_loop = MagicMock()
            mock_widget_with_loop.loop = "I AM THE LOOP"
            mock_app.topLevelWidgets.return_value = [mock_widget_with_loop]
            self.assertEqual(system_config._get_loop_ref(), "I AM THE LOOP")

if __name__ == "__main__":
    unittest.main()
