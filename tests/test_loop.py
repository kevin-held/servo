import unittest
import json
import time
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from PySide6.QtCore import QCoreApplication
from core.loop import CoreLoop, LoopStep

class TestCoreLoopHardened(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.mock_state = MagicMock()
        self.mock_ollama = MagicMock()
        self.mock_tools = MagicMock()
        
        # Hard-hydrate to avoid recursive MagicMock crashes
        self.mock_ollama.model = "test-model"
        self.mock_ollama.total_tokens_used = 100
        self.mock_ollama.num_ctx = 4096
        self.mock_ollama.last_prompt_tokens = 0
        self.mock_ollama.last_response_tokens = 0
        
        self._state_store = {"summarize_history_integrate": "True", "dirty": "False"}
        self.mock_state.get.side_effect = lambda k, d=None: self._state_store.get(k, d)
        self.mock_state.get_session_flag.side_effect = lambda k, d="False": self._state_store.get(k, d)
        self.mock_state.get_conversation_history.return_value = []
        self.mock_state.get_all_state.return_value = {}
        self.mock_state.get_pending_tasks.return_value = []
        
        self.patches = [
            patch("core.identity.get_identity", return_value={"agent_name": "TestServo", "user_name": "Test"}),
            patch("core.sentinel_logger.get_logger", return_value=MagicMock()),
            patch("core.hardware.get_resource_status", return_value={"status": "Stable", "ram_percent": 10}),
            patch("core.config.get_system_defaults", return_value={
                "defaults": {
                    "conversation_history": 20, "chain_limit": 10, "autonomous_loop_limit": 5,
                    "max_auto_continues": 2, "verbosity": "Normal", "ui_show_thinking": True,
                    "summarize_read_enabled": True, "summarize_read_threshold": 5,
                    "context_viewer_history_limit": 10
                },
                "bounds": {}
            })
        ]
        for p in self.patches: p.start()
        
        self.loop = CoreLoop(self.mock_state, self.mock_ollama, self.mock_tools)
        # Mock signals explicitly
        signals = ["step_changed", "trace_event", "response_ready", "tool_called", "error_occurred", "stream_chunk", "stream_started", "stream_finished", "config_changed", "log_event", "telemetry_event"]
        for sig in signals:
            if hasattr(self.loop, sig):
                setattr(self.loop, sig, MagicMock())
                
        self.loop.start_time = time.time()

    def tearDown(self):
        patch.stopall()

    # --- 1. Basic Directives & Logic ---
    @patch("core.loop.time.sleep", return_value=None)
    def test_autonomous_directives(self, mock_sleep):
        # Done path
        self.mock_ollama.chat.return_value = ("Ack.", False)
        d = self.loop._run_cycle({"text": "hi"})
        self.assertEqual(d["action"], "done")
        
        # Chain path
        self.mock_ollama.chat.side_effect = [('{"tool": "t1"}', False), ('{"tool": "t2"}', False)]
        self.mock_tools.execute.return_value = "Result"
        self.loop.autonomous_loop_limit = 1
        d = self.loop._run_cycle({"text": "run tools"})
        self.assertEqual(d["action"], "chain")

    def test_json_resilience_robust(self):
        # hallu trailing brackets
        res = self.loop._parse_tool_call('{"tool":"t"}}}}')
        self.assertEqual(res["tool"], "t")
        # hallu windows paths
        res = self.loop._parse_tool_call('{"tool":"t", "path":"C:\\work"}')
        self.assertEqual(res["path"], "C:\\work")

    def test_act_summarize_guard(self):
        reasoning = {"tool_call": {"tool": "file_read", "args": {"path": "test.txt"}}, "context": {"input": "r", "history": []}, "raw_response": "r"}
        with patch("core.path_utils.resolve") as m_res:
            m_p = MagicMock(spec=Path)
            m_p.is_file.return_value = True
            m_res.return_value = m_p
            with patch("builtins.open", mock_open(read_data=b"1\n2\n3\n4\n5\n6\n7\n")):
                self.mock_ollama.chat.return_value = ("f", False)
                res = self.loop._act(reasoning)
                self.assertTrue(res["tool_args"]["summarize"])

    def test_uptime_fixed(self):
        self.assertGreater(self.loop.start_time, 0)
        sensors = self.loop._build_environmental_sensors({"history": []}, 0)
        self.assertIn("Uptime:", sensors)

    # --- 2. Advanced Convergence (New) ---
    def test_submit_input_interruption(self):
        # Trigger interruption while REASONING
        self.loop._set_step(LoopStep.REASON)
        self.loop.submit_input("stop")
        self.assertTrue(self.loop._cancel_event.is_set())
        self.assertEqual(self.loop.user_interrupts_total, 1)

    @patch("core.hardware.get_resource_status")
    @patch("core.loop.time.sleep", return_value=None)
    def test_hardware_throttling_trigger(self, mock_sleep, mock_hw):
        mock_hw.return_value = {"status": "Critical", "ram_percent": 96, "vram_percent": 96}
        # Force primitive tokens for safe hardware sensor rendering
        self.loop.ollama.total_tokens_used = 100
        self.loop.ollama.num_ctx = 4096
        self.loop.hardware_throttling_enabled = True
        self.mock_ollama.chat.return_value = ("Ack", False)
        
        # Should reduce history and record throttle total
        self.loop.conversation_history = 20
        self.loop._run_cycle({"text": "heavy input"})
        self.assertLess(self.loop.conversation_history, 20)
        self.assertGreater(self.loop.hardware_throttle_total, 0)

    @patch("core.loop.time.sleep", return_value=None)
    def test_auto_continue_recursion(self, mock_sleep):
        # Mock truncated response
        self.mock_ollama.chat.side_effect = [("Part 1", True), ("Part 2", False)]
        self.loop.max_auto_continues = 1
        
        text, truncated = self.loop._call_model("P", [])
        final = self.loop._auto_continue(text, truncated, "P", [], phase="reason")
        
        self.assertEqual(final, "Part 1Part 2")
        self.assertEqual(self.loop.auto_continues_total, 1)

    def test_diagnostic_restart_detection(self):
        # Case 1: Code Update
        with patch("os.path.getmtime", return_value=time.time()):
            res = self.loop._detect_restart_reason()
            self.assertIn("CODE_DEPLOYMENT", res)
            
        # Case 2: Dirty Shutdown
        self._state_store["dirty"] = "True"
        res = self.loop._detect_restart_reason()
        self.assertIn("FAILURE_RECOVERY", res)

if __name__ == "__main__":
    unittest.main()