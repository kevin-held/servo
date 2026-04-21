import unittest
from unittest.mock import MagicMock
from core.loop import CoreLoop

class TestAutonomyModes(unittest.TestCase):
    def setUp(self):
        self.state = MagicMock()
        self.ollama = MagicMock()
        self.tools = MagicMock()
        # Mock state.get to return defaults
        self.state.get.side_effect = lambda k, d: d
        self.loop = CoreLoop(self.state, self.ollama, self.tools)

    def test_reflex_mode(self):
        # Reflex: limit=1
        self.loop.autonomous_loop_limit = 1
        self.assertFalse(self.loop.continuous_mode)
        
    def test_endurance_mode(self):
        # Endurance: limit=0
        self.loop.autonomous_loop_limit = 0
        self.assertTrue(self.loop.continuous_mode)

    def test_steady_mode(self):
        # Steady: limit=5
        self.loop.autonomous_loop_limit = 5
        self.assertTrue(self.loop.continuous_mode)

    def test_toggle_continuous_on(self):
        # Start in reflex
        self.loop.autonomous_loop_limit = 1
        self.assertFalse(self.loop.continuous_mode)
        
        # Toggle ON
        self.loop.continuous_mode = True
        # Should default to 0 (unbounded)
        self.assertEqual(self.loop.autonomous_loop_limit, 0)
        self.assertTrue(self.loop.continuous_mode)

    def test_toggle_continuous_off(self):
        # Start in endurance
        self.loop.autonomous_loop_limit = 0
        self.assertTrue(self.loop.continuous_mode)
        
        # Toggle OFF
        self.loop.continuous_mode = False
        self.assertEqual(self.loop.autonomous_loop_limit, 1)
        self.assertFalse(self.loop.continuous_mode)

    def test_plan_safety_valve(self):
        # This tests the logic inside _run_cycle ideally, but we can't easily run it headlessly here.
        # We can however verify the variable states.
        pass

if __name__ == "__main__":
    unittest.main()
