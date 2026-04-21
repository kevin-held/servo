import sqlite3
import os
import sys

TOOL_NAME        = "memory_manager"
TOOL_DESCRIPTION = "Manage continuous project logic, rules, or scratchpad notes in your persistent Working Memory. This content lives in your context window constantly."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "action": {"type": "string", "enum": ["overwrite", "append", "clear"], "description": "Update behavior."},
    "content": {"type": "string", "description": "The logic, summary, or thoughts."}
}

def execute(action: str, content: str = "") -> str:
    db_path = os.path.join(os.path.dirname(__file__), "..", "state", "state.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = None
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        
        # Make sure the table exists just in case memory manager fires early
        conn.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        
        cur = conn.execute("SELECT value FROM state WHERE key = 'working_memory'")
        row = cur.fetchone()
        current_mem = row[0] if row else ""
        
        new_mem = current_mem
        if action == "clear":
            new_mem = ""
            msg = "Working memory cleared."
        elif action == "append":
            new_mem = (current_mem + "\n" + content).strip()
            
            # Auto-summarize if working memory grows excessively large
            if len(new_mem) > 1500:
                try:
                    import requests
                    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
                    from core.ollama_client import OllamaClient
                    
                    # Dynamically detect what is ACTUALLY loaded right now to avoid huge VRAM swaps
                    loaded_model = "qwen3.5:27b"
                    try:
                        ps_req = requests.get("http://localhost:11434/api/ps", timeout=2).json()
                        ps_models = ps_req.get("models", [])
                        if ps_models:
                            loaded_model = ps_models[0].get("name", loaded_model)
                    except Exception:
                        pass

                    client = OllamaClient(model=loaded_model)
                    prompt = f"Compress this working memory to under 1500 chars while retaining all critical project logic, rules, and facts. Return ONLY the compressed text with no conversational intro:\n\n{new_mem}"
                    compressed_text, _ = client.chat(prompt, [], timeout=60)
                    
                    if compressed_text:
                        new_mem = compressed_text.strip()
                        msg = f"Appended and safely auto-summarized memory to {len(new_mem)} chars using {loaded_model}."
                    else:
                        msg = "Successfully appended to working memory."
                except Exception as e:
                    msg = f"Appended to working memory (summarization bypassed: {e})"
            else:
                msg = "Successfully appended to working memory."
        elif action == "overwrite":
            new_mem = content
            msg = "Successfully OVERWRITTEN working memory."
            
        conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", ("working_memory", new_mem))
        conn.commit()

        # v1.0.0 (D-20260421-17): Automatic Functional Snapshot
        # Log the entire content to the structured Sentinel log for "eyes-on" recall.
        try:
            from core.sentinel_logger import get_logger
            get_logger().log("INFO", "memory.snapshot", "Working memory updated", {"content": new_mem})
            msg += " (Snapshot captured in System Logs)"
        except Exception:
            pass

    except Exception as e:
        msg = f"Database Error: {e}"
    finally:
        if conn:
            conn.close()
        
    return msg
