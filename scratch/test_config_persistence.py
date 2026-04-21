import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on the path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.loop import CoreLoop
from tools import system_config

class TestConfigPersistence(unittest.TestCase):
    def setUp(self):
        # Create a dummy loop
        self.loop = MagicMock(spec=CoreLoop)
        self.loop.ollama = MagicMock()
        self.loop.state = MagicMock()
        self.loop.ollama.model = "test-model"
        self.loop.ollama.temperature = 0.5
        self.loop.ollama.num_predict = 1024
        self.loop.conversation_history = 10
        self.loop.chain_limit = 5
        self.loop.autonomous_loop_limit = 0
        self.loop.max_auto_continues = 2
        self.loop.verbosity = "Normal"
        self.loop.continuous_mode = False
        self.loop.stream_enabled = True
        self.loop.hardware_throttling_enabled = False
        self.loop.hardware_throttle_threshold_enter = 95.0
        self.loop.hardware_throttle_threshold_exit = 90.0
        
        # Ensure state.get returns serializable numeric strings to satisfy bounds checking
        self.loop.state.get.side_effect = lambda key, default=None: default
        
        # Patch the _get_loop_ref in system_config
        self.patcher = patch("tools.system_config._get_loop_ref", return_value=self.loop)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        # Clean up test config files
        test_file = Path("configs/test_preset.json")
        if test_file.exists():
            test_file.unlink()

    def test_save_and_load(self):
        # 1. Save
        result = system_config.execute(operation="save", value="test_preset.json")
        self.assertIn("saved", result)
        
        # Verify file exists
        test_file = Path("configs/test_preset.json")
        self.assertTrue(test_file.exists())
        
        # 2. Modify values in loop
        self.loop.ollama.temperature = 0.9
        self.loop.ollama.num_predict = 2048
        
        # 3. Load
        result = system_config.execute(operation="load", value="test_preset.json")
        self.assertIn("loaded", result)
        
        # 4. Verify values restored
        self.assertEqual(self.loop.ollama.temperature, 0.5)
        self.assertEqual(self.loop.ollama.num_predict, 1024)

if __name__ == "__main__":
    unittest.main()
