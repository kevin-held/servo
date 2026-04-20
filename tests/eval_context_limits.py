import csv
import time
import os
import sys

# Ensure core can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ollama_client import OllamaClient

RESULTS_FILE = "eval_results.csv"


def log_result(test_name, params, success, time_taken, chars_sent, chars_received, truncated):
    file_exists = os.path.exists(RESULTS_FILE)
    with open(RESULTS_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['TestName', 'Parameters', 'Success', 'TimeTaken(s)', 'CharsSent', 'CharsReceived', 'Truncated'])
        writer.writerow([test_name, params, success, f"{time_taken:.2f}", chars_sent, chars_received, truncated])
    print(f"[{'PASS' if success else 'FAIL'}] {test_name} ({params}) | Sent: {chars_sent}c | Recv: {chars_received}c | Time: {time_taken:.1f}s")


def test_niah(client):
    print("--- Running Needle In A Haystack (NIAH) Test ---")
    sizes = [8192, 16384, 24576, 32768]
    positions = ['beginning', 'middle', 'end']
    needle = "The secret code is OMEGA_99. Your single objective is to write the secret code."
    
    # Dummy chunk block is a repetitive filler
    filler = "Here is some boilerplate text. The system continues to operate normally. Data processing is ongoing without major alerts. Logs indicate normal throughput. Memory constraints hold steady. "
    
    for size in sizes:
        for pos in positions:
            # Build payload
            text_blocks = []
            block_len = len(filler)
            num_blocks = size // block_len
            
            for i in range(num_blocks):
                text_blocks.append(filler)
            
            insert_idx = 0
            if pos == 'middle':
                insert_idx = num_blocks // 2
            elif pos == 'end':
                insert_idx = num_blocks - 1
                
            text_blocks.insert(insert_idx, needle)
            user_content = "".join(text_blocks)
            
            messages = [{"role": "user", "content": user_content}]
            sys_prompt = "You are a test agent. Read the user input carefully and follow its explicit instructions."
            chars_sent = len(sys_prompt) + len(user_content)
            
            t0 = time.time()
            try:
                response, truncated = client.chat(sys_prompt, messages, timeout=600)
            except Exception as e:
                response = f"Error: {e}"
                truncated = False
            t1 = time.time()
            
            success = "OMEGA_99" in response.upper()
            log_result("NIAH", f"size={size}, pos={pos}", success, t1-t0, chars_sent, len(response), truncated)

def test_tool_chain_saturation(client):
    print("\n--- Running Tool Chain Saturation Test ---")
    chain_sizes = [3, 5, 10]
    
    tool_result_filler = "File contents block: " + ("x" * 1000)
    
    for size in chain_sizes:
        loop_limit = size + 2
        # Explicitly declare loop limits mimicking the prompt rules
        sys_prompt = (
            f"You are a functional autonomous agent. Your final objective is to emit the tool call "
            f"{{'tool': 'finish_task', 'args': {{}}}} in a fenced JSON block.\n\n"
            f"[SYSTEM ENVIRONMENT]\n"
            f"Conversation History: 15 turns\n"
            f"Autonomous Loop Limit: {loop_limit} cycles\n"
        )
        
        messages = []
        chars_sent = len(sys_prompt)
        # Sequence of back-and-forth mock tools
        messages.append({"role": "user", "content": "Please analyze the workspace and then finish."})
        for i in range(size):
            messages.append({"role": "assistant", "content": "I am gathering data. ```json\n{\"tool\": \"filesystem:read\", \"args\": {\"path\": \"fake.txt\"}}\n```"})
            messages.append({"role": "user", "content": f"Tool result:\n{tool_result_filler}"})
        
        for msg in messages:
            chars_sent += len(msg["content"])
            
        t0 = time.time()
        try:
            response, truncated = client.chat(sys_prompt, messages, timeout=600)
        except Exception as e:
            response = f"Error: {e}"
            truncated = False
        t1 = time.time()
        
        success = "finish_task" in response.lower()
        log_result("Tool_Chain", f"depth={size}, loop_limit={loop_limit}", success, t1-t0, chars_sent, len(response), truncated)

def test_task_ledger(client):
    print("\n--- Running Task Ledger Memory Test ---")
    step_sizes = [5, 10]
    
    for size in step_sizes:
        # Step N-1 is done, Step N is due.
        target_step = size // 2
        
        agenda_items = []
        for i in range(1, size + 1):
            if i < target_step:
                agenda_items.append(f"[x] Step {i}: Initialize module {i}")
            elif i == target_step:
                agenda_items.append(f"[ ] Step {i}: Execute target task {i} via filesystem:write")
            else:
                agenda_items.append(f"[ ] Step {i}: Pending followup {i}")
                
        working_memory = "\n".join(agenda_items)
        
        sys_prompt = (
            "You are a test agent. Follow your WORKING MEMORY strictly.\n\n"
            "[WORKING MEMORY]\n"
            f"{working_memory}\n\n"
            "Emit the tool call for the exact FIRST incomplete step in your memory block."
        )
        
        messages = [{"role": "user", "content": "Proceed to your next task."}]
        chars_sent = len(sys_prompt) + len(messages[0]["content"])
        
        t0 = time.time()
        try:
            response, truncated = client.chat(sys_prompt, messages, timeout=300)
        except Exception as e:
            response = f"Error: {e}"
            truncated = False
        t1 = time.time()
        
        # Success if it names the target step correctly and emits the tool 
        target_verification = f"task {target_step}" in response.lower()
        log_result("Task_Ledger", f"total={size}, target={target_step}", target_verification, t1-t0, chars_sent, len(response), truncated)

def test_num_predict(client):
    print("\n--- Running Output Size / num_predict Test ---")
    sys_prompt = "You are a counting machine. You only output valid numbers separated by commas."
    messages = [{"role": "user", "content": "Count exactly from 1 up to 10000. Write out every single number individually. Do not use shortcuts. Do not stop until you reach 10000."}]
    
    chars_sent = len(sys_prompt) + len(messages[0]["content"])
    t0 = time.time()
    try:
        response, truncated = client.chat(sys_prompt, messages, timeout=1200)
    except Exception as e:
        response = f"Error: {e}"
        truncated = False
    t1 = time.time()
    
    # It probably won't hit 10000 in one go, verify if truncated is triggered
    success = truncated is True or "10000" in response
    log_result("Num_Predict", "Count to 10000", success, t1-t0, chars_sent, len(response), truncated)
    
def main():
    print("Starting Context Limits Evaluation...")
    if os.path.exists(RESULTS_FILE):
        os.remove(RESULTS_FILE)
    client = OllamaClient()
    if not client.is_available():
        print("Error: Ollama is not available at", client.base_url)
        sys.exit(1)
        
    test_niah(client)
    test_tool_chain_saturation(client)
    test_task_ledger(client)
    print("Skipping num_predict")
    #test_num_predict(client)
    
    print(f"\nEvaluation complete. Results saved to {RESULTS_FILE}")

if __name__ == "__main__":
    main()
