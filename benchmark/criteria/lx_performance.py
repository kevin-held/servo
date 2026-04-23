import time
import statistics
from typing import List, Dict, Any, Callable

def calculate_metrics(latencies: List[float]) -> Dict[str, Any]:
    """
    Calculates Mu (mean), Sigma (std dev), and CV (jitter) for a sample of latencies.
    """
    if not latencies:
        return {"pass": False, "reason": "No latency data"}

    mu = statistics.mean(latencies)
    sigma = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
    cv = (sigma / mu) if mu > 0 else 0.0

    # D-20260423: Coefficient of Variation threshold for "Stability"
    # Legacy Loop target: CV < 0.15
    # New Core target: CV < 0.05
    pass_threshold = 0.15 
    is_pass = cv <= pass_threshold

    return {
        "metric": "lx_performance",
        "pass": is_pass,
        "mu_ms": round(mu * 1000, 2),
        "sigma_ms": round(sigma * 1000, 2),
        "jitter_pct": round(cv * 100, 2),
        "count": len(latencies),
        "threshold_pct": pass_threshold * 100
    }

def benchmark_function(func: Callable, iterations: int = 5, *args, **kwargs) -> Dict[str, Any]:
    """
    Wraps a function call and measures performance over multiple iterations.
    """
    latencies = []
    for i in range(iterations):
        start = time.perf_counter()
        func(*args, **kwargs)
        end = time.perf_counter()
        latencies.append(end - start)
    
    return calculate_metrics(latencies)

if __name__ == "__main__":
    # Self-test: simulate a stable loop vs a jittery one
    stable = [0.100, 0.101, 0.099, 0.100, 0.102]
    jittery = [0.100, 0.200, 0.050, 0.150, 0.100]
    
    print("Stable Benchmark:", calculate_metrics(stable))
    print("Jittery Benchmark:", calculate_metrics(jittery))
