import pytest
from unittest.mock import MagicMock, patch
from core.lx_cognates import lx_Observe, lx_Reason

def test_lx_observe_idle_state():
    """Test OBSERVE when there is no perception and no halt signal."""
    mock_core = MagicMock()
    mock_core.perception_queue = None
    mock_core.perception_cond = None
    mock_core.halt_event = None
    mock_core.ollama = None
    mock_core._active_store = None
    mock_core.config = {"observe_roots": []} # Fast observe
    
    observe = lx_Observe(mock_core)
    state = {}
    
    delta = observe.execute(state)
    assert delta["current_step"] == "REASON"
    assert delta["observation_kind"] == "user_input"
    assert delta["perception_text"] == ""
    assert "halt" not in delta

def test_lx_observe_halt_signal():
    """Test OBSERVE respects the halt signal."""
    mock_core = MagicMock()
    mock_core.perception_queue = []
    mock_core.perception_cond = MagicMock()
    mock_core.halt_event = MagicMock()
    mock_core.halt_event.is_set.return_value = True
    mock_core.ollama = None
    mock_core.config = {"observe_roots": []}
    
    observe = lx_Observe(mock_core)
    delta = observe.execute({})
    assert delta["current_step"] == "REASON"
    assert delta["halt"] is True

def test_lx_observe_pending_tool_output():
    """Test OBSERVE processes pending tool output correctly."""
    mock_core = MagicMock()
    mock_core.perception_queue = []
    mock_core.config = {"observe_roots": []}
    
    observe = lx_Observe(mock_core)
    state = {
        "pending_tool_output": {
            "kind": "tool_output",
            "tool_result": "Success"
        }
    }
    
    delta = observe.execute(state)
    assert delta["observation_kind"] == "tool_output"
    assert "Success" in delta["perception_text"]
    assert delta["pending_tool_output"] is None

def test_lx_reason_fallback_pick():
    """Test REASON falls back to random/explore when ollama is unavailable."""
    mock_core = MagicMock()
    mock_core.ollama = None
    mock_core.config = {"epsilon_0": 1.0, "lambda_decay": 0.0} # Always explore
    
    mock_store = MagicMock()
    mock_store.count_success_vectors.return_value = 0
    mock_core._active_store = mock_store
    
    reason = lx_Reason(mock_core)
    
    with patch("core.lx_cognates.random.random", return_value=0.1):
        delta = reason.execute({})
    
    assert delta["current_step"] == "ACT"
    assert delta["decision_mode"] == "explore"
    assert delta["planned_tool"] is not None

def test_lx_reason_llm_chain():
    """Test REASON properly parses a tool chain from the LLM."""
    mock_core = MagicMock()
    mock_ollama = MagicMock()
    mock_ollama.chat.return_value = (
        '```json\n{"tool": "file_write", "args": {}}\n```\n'
        '```json\n{"tool": "task", "args": {"action": "complete"}}\n```',
        False
    )
    mock_core.ollama = mock_ollama
    mock_core.config = None
    mock_core._active_store = MagicMock()
    
    reason = lx_Reason(mock_core)
    
    delta = reason.execute({})
    
    assert delta["current_step"] == "ACT"
    assert delta["decision_mode"] == "llm_tool_chain"
    assert delta["planned_tool"] == "file_write"
    assert len(delta["chained_calls"]) == 1
    assert delta["chained_calls"][0]["tool"] == "task"

def test_lx_reason_llm_chain_invalid_tail():
    """Test REASON drops non-bookkeeping tools from the tail of a chain."""
    mock_core = MagicMock()
    mock_ollama = MagicMock()
    mock_ollama.chat.return_value = (
        '```json\n{"tool": "file_write", "args": {}}\n```\n'
        '```json\n{"tool": "file_read", "args": {}}\n```', # Invalid tail
        False
    )
    mock_core.ollama = mock_ollama
    mock_core.config = None
    mock_core._active_store = MagicMock()
    
    reason = lx_Reason(mock_core)
    delta = reason.execute({})
    
    assert delta["current_step"] == "ACT"
    assert delta["decision_mode"] == "llm_tool"
    assert delta["planned_tool"] == "file_write"
    assert len(delta["chained_calls"]) == 0
    assert "dropped non-bookkeeping tail call(s): file_read" in delta["chain_warning"]

