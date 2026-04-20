import time
import sys
from pathlib import Path

# Fix python path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.history_compressor import _build_system_rules, _build_user_content
from tools.summarizer import summarize

def run_fidelity_test():
    print("Starting Summarizer Fidelity Test...")
    
    # 1. Construct 15 raw conversation turns
    turns = []
    
    # Early turns
    turns.append({"role": "user", "content": "Our main objective for this session is to deploy the frontend to Vercel."})
    turns.append({"role": "assistant", "content": "Understood. I will begin by checking the local Vercel CLI configuration."})
    turns.append({"role": "user", "content": "Tool result: ERROR: Vercel CLI not found on PATH."})
    
    # Noise loop (simulating intermediate work)
    turns.append({"role": "assistant", "content": "I will try installing it via npm."})
    turns.append({"role": "user", "content": "Tool result: " + "npm WARN deprecated..." * 30})
    turns.append({"role": "assistant", "content": "It seems there are dependency issues. Let me read the package.json."})
    turns.append({"role": "user", "content": "Tool result: package.json contents block."})
    
    # Mid-chain Pivot
    turns.append({"role": "user", "content": "Wait, nevermind about Vercel. Pivot to deploying on Netlify instead."})
    turns.append({"role": "assistant", "content": "Acknowledged. Pivoting away from Vercel. I will use the Netlify CLI instead."})
    
    # More noise
    turns.append({"role": "user", "content": "Tool result: " + "junk code output " * 50})
    turns.append({"role": "assistant", "content": "I will initialize the project configuration."})
    turns.append({"role": "user", "content": "Tool result: file created."})
    
    # End-chain target
    turns.append({"role": "assistant", "content": "I am writing the deployment configuration to netlify.toml."})
    turns.append({"role": "user", "content": "Tool result: SUCCESS. Site is now live at https://custom-netlify-test.netlify.app."})
    turns.append({"role": "assistant", "content": "The deployment is complete. What would you like to do next?"})
    
    
    # 2. Format with exact production logic
    system_rules = _build_system_rules()
    user_content = _build_user_content(turns, prior_summary=None)
    
    print("\n--- Running Summarizer ---")
    start_t = time.time()
    summary, model_used = summarize(user_content, system_rules)
    end_t = time.time()
    
    print(f"\nModel Used: {model_used}")
    print(f"Time Taken: {end_t - start_t:.1f}s")
    print(f"Summary generated ({len(summary)} chars):\n")
    print("="*60)
    print(summary)
    print("="*60)
    
    # 3. Assert facts
    print("\n--- Fact Fidelity Assertions ---")
    
    summary_lower = summary.lower()
    
    # Fact 1: Was Vercel mentioned as a failed or pivoted initial instruction?
    has_vercel = "vercel" in summary_lower
    # Fact 2: Did it catch the Pivot to Netlify?
    has_netlify = "netlify" in summary_lower
    # Fact 3: Did it save the final success URL?
    has_url = "custom-netlify-test" in summary_lower
    
    print(f"1. Captured 'Vercel' context? : {'[PASS]' if has_vercel else '[FAIL]'}")
    print(f"2. Captured 'Netlify' pivot?  : {'[PASS]' if has_netlify else '[FAIL]'}")
    print(f"3. Captured live URL outcome? : {'[PASS]' if has_url else '[FAIL]'}")
    
    print("\nDone.")

if __name__ == "__main__":
    run_fidelity_test()
