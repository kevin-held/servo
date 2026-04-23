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
    #
    # D-20260423 (Phase C): each sample is paired with its expected pass/fail
    # so the regression sample ("I'm sorry, as an AI...") — which is DESIGNED
    # to fail the lexicon check — no longer drags overall_pass down with it.
    # The lexicon module is the unit-under-test; it passes iff each sample's
    # observed pass matches its declared expected_pass.
    print("Running Lexicon Audit...", end=" ")
    lex_samples = [
        ("The project mapping is complete. Proceeding with Directive 2.", True),
        ("I'm sorry, as an AI model I cannot do that.",                    False),
        ("Executing map_project(path='.')",                                True),
    ]
    lex_report = {"metric": "lx_lexicon_batch", "samples": []}
    for text, expected in lex_samples:
        result = lx_lexicon.audit_text(text)
        result["expected_pass"] = expected
        result["module_pass"] = (result["pass"] == expected)
        lex_report["samples"].append(result)
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

    # Lexicon module pass: observed == expected across all samples. The
    # regression sample is SUPPOSED to fail the prose filter; that's the
    # filter doing its job, not an audit failure.
    lex_pass = all(s["module_pass"] for s in lex_report["samples"])
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
