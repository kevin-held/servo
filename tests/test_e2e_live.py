import os
import sys
import time
import shutil
import tempfile
import threading
from pathlib import Path

# Setup paths so we can import core modules
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import QCoreApplication

from core.state import StateStore
from core.ollama_client import OllamaClient
from core.tool_registry import ToolRegistry
from core.loop import CoreLoop

app = QCoreApplication([])

# Check if model is running
_test_client = OllamaClient()
if not _test_client.is_available():
    print("Ollama is not running. E2E tests aborted.")
    sys.exit(1)


def run_test_harness(test_name: str, objective: str, verification_fn, max_wait: int = 60, chain_limit: int = 15) -> bool:
    print(f"\n==============================================")
    print(f"Running E2E: {test_name}")
    print(f"Goal: {objective}")
    
    tmp_path = tempfile.mkdtemp()
    db_path = os.path.join(tmp_path, "state.db")
    chroma_path = os.path.join(tmp_path, "chroma")
    
    state = StateStore(db_path, chroma_path)
    ollama = OllamaClient()
    tools = ToolRegistry()
    loop = CoreLoop(state, ollama, tools)
    
    loop.chain_limit = chain_limit
    loop.autonomous_loop_limit = chain_limit
    
    completion_flag = threading.Event()
    
    def on_ready(v1, v2):
        print(f"[CoreLoop] Response emitted: {v1[:200].encode('ascii', 'replace').decode()}...")
        completion_flag.set()
        
    def on_trace(step, msg):
        print(f"[Trace {step}] {msg.encode('ascii', 'replace').decode()}")

    def on_tool(name, args, result):
        print(f"[Tool] {name} called with {args}")
        
    def on_err(e):
        print(f"CoreLoop Error: {e}")
        completion_flag.set()
        
    loop.response_ready.connect(on_ready)
    loop.trace_event.connect(on_trace)
    loop.tool_called.connect(on_tool)
    loop.error_occurred.connect(on_err)
    
    loop.start()
    
    # Give the objective
    loop.submit_input(f"E2E TEST OBJECTIVE:\n{objective}\n\nDo not ask for verification, just complete the entire objective natively via tools and then reply back indicating you are finished. Use the exact paths provided.")
    
    # Wait for the agent to finish its chains (must pump PySide events)
    start_t = time.time()
    while not completion_flag.is_set():
        app.processEvents()
        time.sleep(0.01)
        if time.time() - start_t > max_wait:
            break
            
    elapsed = time.time() - start_t
    
    loop.stop()
    loop.wait() # join thread safely
    
    if not completion_flag.is_set():
        print(f"[{test_name}] TIMEOUT after {elapsed:.1f}s")
        success = False
    else:
        success = verification_fn(tmp_path)
    
    print(f"[{'PASS' if success else 'FAIL'}] {test_name} in {elapsed:.1f}s")
    
    # Cleanup
    try:
        shutil.rmtree(tmp_path)
    except Exception:
        pass
        
    return success

# ────────────────────────────────────────────────────────
# Scenarios
# ────────────────────────────────────────────────────────

def test_simple_e2e():
    tmp_path = tempfile.mkdtemp(dir="tests")
    rel_tmp = os.path.relpath(tmp_path).replace("\\", "/")
    def verify(tmp_path):
        target = os.path.join(tmp_path, "e2e_simple.txt")
        if not os.path.exists(target):
            return False
        with open(target, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return "E2E_PASS" in content

    return run_test_harness(
        test_name="Simple_Create_File",
        objective=f"Create a file identically named '{rel_tmp}/e2e_simple.txt'. Write the exact string 'E2E_PASS' into it using the filesystem tool.",
        verification_fn=lambda _: verify(tmp_path),
        max_wait=60, # allow up to a minute for generation
        chain_limit=5
    )

def test_medium_e2e():
    def verify(tmp_path):
        target = os.path.join(tmp_path, "e2e_output.txt")
        if not os.path.exists(target):
            return False
        with open(target, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return "60" in content

    # Setup the problem file
    tmp_path = tempfile.mkdtemp(dir="tests")
    rel_tmp = os.path.relpath(tmp_path).replace("\\", "/")
    input_file_abs = os.path.join(tmp_path, "e2e_input.txt")
    with open(input_file_abs, "w") as f:
        f.write("10\n20\n30\n")

    return run_test_harness(
        test_name="Medium_Read_Compute_Write",
        objective=f"Read the file '{rel_tmp}/e2e_input.txt'. Add the listed numbers together. Write the final computed integer into a new file named '{rel_tmp}/e2e_output.txt'.",
        verification_fn=lambda _: verify(tmp_path), 
        max_wait=120,
        chain_limit=10
    )

def test_hard_e2e():
    tmp_path = tempfile.mkdtemp(dir="tests")
    rel_tmp = os.path.relpath(tmp_path).replace("\\", "/")
    os.makedirs(os.path.join(tmp_path, "logs"))
    os.makedirs(os.path.join(tmp_path, "logs", "2026", "april"))
    
    # Dummy files
    with open(os.path.join(tmp_path, "logs", "access.log"), "w") as f:
        f.write("User logged in\nUser logged out")
        
    with open(os.path.join(tmp_path, "logs", "2026", "april", "srv.log"), "w") as f:
        f.write("Boot sequence initiated...\nCRITICAL_BUG detected at line 42\nRebooting...")

    def verify(tmp_path):
        target = os.path.join(tmp_path, "logs", "2026", "april", "srv.log")
        if not os.path.exists(target):
            return False
        with open(target, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return "CRITICAL_BUG" not in content and "RESOLVED_BUG" in content

    return run_test_harness(
        test_name="Hard_Deep_Search_And_Patch",
        objective=f"Scan the directory '{rel_tmp}/logs'. Recursively find the file containing the exact string 'CRITICAL_BUG'. Do not guess; list the folder and read the files. Once found, edit that file to replace the string 'CRITICAL_BUG' with 'RESOLVED_BUG'.",
        verification_fn=lambda _: verify(tmp_path),
        max_wait=240,
        chain_limit=15
    )

if __name__ == "__main__":
    print("Beginning E2E Live Test Suite...")
    res1 = test_simple_e2e()
    res2 = test_medium_e2e()
    res3 = test_hard_e2e()
    
    total = sum([res1, res2, res3])
    print(f"\nFinal Score: {total}/3 PASSED")
    sys.exit(0 if total == 3 else 1)
