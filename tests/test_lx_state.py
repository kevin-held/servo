import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.lx_state import lx_StateStore

@pytest.fixture
def temp_state_dir(tmp_path):
    return tmp_path / "state"

@pytest.fixture
def mock_chroma():
    mock_cdb = MagicMock()
    mock_client = MagicMock()
    mock_cdb.PersistentClient.return_value = mock_client
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    
    with patch.dict("sys.modules", {"chromadb": mock_cdb}):
        yield mock_cdb, mock_client, mock_collection

def test_lx_state_init_and_json_persistence(temp_state_dir):
    """Test that lx_StateStore properly initializes, creates JSON, and applies deltas."""
    store = lx_StateStore(profile="test_prof", state_dir=str(temp_state_dir))
    
    # Check default state
    assert store.current_state == {"current_step": "OBSERVE", "last_trace": None}
    
    store.sync_vector()
    # Check files created
    assert temp_state_dir.exists()
    profile_path = temp_state_dir / "lx_state_test_prof.json"
    assert profile_path.exists()
    
    # Apply delta
    store.apply_delta({"current_step": "PROPOSE", "new_key": "value"})
    assert store.current_state["current_step"] == "PROPOSE"
    assert store.current_state["new_key"] == "value"
    
    # Verify sync_vector wrote to disk
    with open(profile_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["current_step"] == "PROPOSE"
    assert disk_data["new_key"] == "value"
    
    # Test load mirror on new instance
    store2 = lx_StateStore(profile="test_prof", state_dir=str(temp_state_dir))
    assert store2.current_state["current_step"] == "PROPOSE"
    assert store2.current_state["new_key"] == "value"

def test_lx_state_chroma_degradation(temp_state_dir):
    """Test that lx_StateStore degrades gracefully if chromadb is missing or fails."""
    # Force chromadb import to fail
    with patch.dict("sys.modules", {"chromadb": None}):
        store = lx_StateStore(profile="no_chroma", state_dir=str(temp_state_dir))
        assert store._chroma_client is None
        assert store._procedural_wins is None
        assert "_chroma_degraded" in store.current_state
        
        # Method calls should safely return False/empty when degraded
        assert store.commit_success_vector("sig", "tool", 0.9, {}) is False
        assert store.query_success_vectors("sig") == []
        assert store.count_success_vectors() == 0

def test_lx_state_legacy_config(temp_state_dir):
    """Test reading from the legacy state.db."""
    # Create a mock legacy state.db
    legacy_db = temp_state_dir / "state.db"
    temp_state_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(legacy_db)
    conn.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO state (key, value) VALUES ('test_key', 'legacy_value')")
    conn.commit()
    conn.close()
    
    store = lx_StateStore(profile="test_prof", state_dir=str(temp_state_dir), legacy_config_path=str(legacy_db))
    
    val = store.get_legacy_config("test_key")
    assert val == "legacy_value"
    
    val_missing = store.get_legacy_config("missing_key", default="fallback")
    assert val_missing == "fallback"

def test_lx_state_turn_persistence(temp_state_dir):
    """Test SQLite turn recording and querying."""
    store = lx_StateStore(profile="turn_test", state_dir=str(temp_state_dir))
    
    # Record a turn
    success = store.record_turn(
        perception_text="I saw a file",
        observation_kind="file_read",
        response_text="I read it",
        tool_name="read_tool",
        status="success"
    )
    assert success is True
    
    # Query turns
    turns = store.query_turns(limit=10)
    assert len(turns) == 1
    assert turns[0]["perception_text"] == "I saw a file"
    assert turns[0]["tool_name"] == "read_tool"
    assert "timestamp" in turns[0]

def test_lx_state_chroma_success_vector_mocked(temp_state_dir, mock_chroma):
    """Test chromadb interactions with a mocked chromadb client."""
    mock_cdb, mock_client, mock_collection = mock_chroma
    store = lx_StateStore(profile="mock_chroma_test", state_dir=str(temp_state_dir))
    
    # Test successful commit
    res = store.commit_success_vector("test_sig", "test_tool", 0.9, {"outcome": "ok"}, embedding=[0.1]*768)
    assert res is True
    mock_collection.add.assert_called_once()
    
    # Test query
    mock_collection.get.return_value = {"metadatas": [{"tool_name": "test_tool", "reward": 0.9}]}
    results = store.query_success_vectors("test_sig")
    assert len(results) == 1
    assert results[0]["tool_name"] == "test_tool"
