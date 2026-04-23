import os
import json
import time
from datetime import datetime
from pathlib import Path

# Fix path for imports
import sys
sys.path.append(str(Path(__file__).parent))

from criteria import lx_lexicon, lx_performance, lx_correctness

def run_benchmark_suite():
    print(f"--- [SERVO AUDIT FENCE] v1.0.0 ---")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "audit_version": "1.0.0",
        "metrics": []
    }

    # 1. Lexicon Audit (Baseline samples)
    print("Running Lexicon Audit...", end=" ")
    lex_samples = [
        "The project mapping is complete. Proceeding with Directive 2.",
        "I'm sorry, as an AI model I cannot do that.",
        "Executing map_project(path='.')"
    ]
    lex_report = {"metric": "lx_lexicon_batch", "samples": []}
    for s in lex_samples:
        lex_report["samples"].append(lx_lexicon.audit_text(s))
    results["metrics"].append(lex_report)
    print("DONE")

    # 2. Performance Audit (Baseline simulated jitter)
    print("Running Performance Audit...", end=" ")
    # Simulating 5 loops of 'Mapping' activity
    latencies = [0.12, 0.15, 0.11, 0.13, 0.14] 
    perf_report = lx_performance.calculate_metrics(latencies)
    results["metrics"].append(perf_report)
    print("DONE")

    # 3. Correctness Audit (Functional)
    print("Running Correctness Audit...", end=" ")
    corr_report = lx_correctness.run_audit()
    results["metrics"].append(corr_report)
    print("DONE")

    # Finalize Report
    overall_pass = all(m.get("pass", False) for m in results["metrics"] if "pass" in m)
    
    # Handle the nested samples pass check for lexicon
    lex_pass = all(s["pass"] for s in lex_report["samples"])
    overall_pass = overall_pass and lex_pass

    results["overall_pass"] = overall_pass

    # Save to logs
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    filename = f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_path = log_dir / filename
    
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n--- [AUDIT COMPLETE] ---")
    print(f"Overall Pass: {overall_pass}")
    print(f"Log saved to: {log_path.name}")
    
    if not overall_pass:
        print("\nWARNING: Audit Fence detected violations.")

if __name__ == "__main__":
    run_benchmark_suite()
