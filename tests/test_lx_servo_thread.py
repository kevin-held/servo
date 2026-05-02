import pytest
from unittest.mock import MagicMock, patch

from core.lx_servo_thread import ServoCoreThread

@pytest.fixture
def mock_core():
    with patch("core.lx_servo_thread.ServoCore") as mock:
        yield mock

@pytest.fixture
def mock_lx_state():
    with patch("core.lx_servo_thread.lx_StateStore", autospec=True) as mock:
        yield mock

def test_servo_thread_init_and_signals(mock_core, mock_lx_state):
    """Test ServoCoreThread initializes properly and maps hooks."""
    mock_state = MagicMock()
    mock_state.profile = "test_profile"
    
    # We patch QThread to avoid needing a QApplication instance in CI
    with patch("core.lx_servo_thread.QThread"):
        thread = ServoCoreThread(state=mock_state, config={})
        
        # Verify lx_StateStore was created with right profile
        mock_lx_state.assert_called_with(profile="test_profile", config=thread._core.config)
        
        # Verify hooks were bound
        assert hasattr(thread._core, "response_ready_hook")
        assert hasattr(thread._core, "telemetry_hook")

def test_servo_thread_submit_input(mock_core, mock_lx_state):
    """Test submit_input forwards properly to the underlying core."""
    with patch("core.lx_servo_thread.QThread"):
        thread = ServoCoreThread(state=MagicMock())
        
        # Connect a mock to the signal
        mock_trace_emit = MagicMock()
        thread.trace_event = MagicMock()
        thread.trace_event.emit = mock_trace_emit
        
        # Submit input
        thread.submit_input("Hello Core", "fake_b64")
        
        # Check internal debug queue
        assert len(thread._pending_inputs) == 1
        assert thread._pending_inputs[0]["text"] == "Hello Core"
        
        # Verify signal emitted
        mock_trace_emit.assert_called_with("PERCEIVE", "[Servo path] Input received: 10 chars")
        
        # Verify core was called
        thread._core.submit_perception.assert_called_once()
        called_arg = thread._core.submit_perception.call_args[0][0]
        assert called_arg["text"] == "Hello Core"
        assert called_arg["kind"] == "user_input"

def test_servo_thread_stop_and_cleanup(mock_core, mock_lx_state):
    """Test stop() propagates halt to core."""
    with patch("core.lx_servo_thread.QThread"):
        thread = ServoCoreThread(state=MagicMock())
        
        thread.stop()
        assert thread._stop_requested is True
        thread._core.signal_halt.assert_called_once()
        
        thread.cleanup()
        assert thread._core.signal_halt.call_count == 2

def test_servo_thread_run_watchdog(mock_core, mock_lx_state):
    """Test run() attaches the stop watchdog to apply_delta."""
    with patch("core.lx_servo_thread.QThread"):
        thread = ServoCoreThread(state=MagicMock())
        
        mock_step_emit = MagicMock()
        thread.step_changed = MagicMock()
        thread.step_changed.emit = mock_step_emit
        
        mock_trace_emit = MagicMock()
        thread.trace_event = MagicMock()
        thread.trace_event.emit = mock_trace_emit
        
        # Setup a mock store with apply_delta
        store = thread._lx_state
        mock_apply = MagicMock()
        store.apply_delta = mock_apply
        
        # Simulate run()
        thread.run()
        
        # Verify signals
        assert mock_step_emit.call_count == 2
        mock_step_emit.assert_called_with("OBSERVE")
        
        # Verify watchdog intercepted apply_delta
        # Let's call it manually to see if it injects halt
        thread._stop_requested = True
        store.apply_delta({"key": "value"})
        
        mock_apply.assert_called_with({"key": "value", "halt": True})
        
        # Verify run_cycle was called
        thread._core.run_cycle.assert_called_once_with(store)
