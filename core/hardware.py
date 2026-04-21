import psutil
import subprocess

def get_resource_status(
    prev_status: str = "Stable",
    enter_threshold: float = 95.0,
    exit_threshold: float = 90.0,
) -> dict:
    """Computes whether the system is in a 'Critical' state requiring context reduction.

    Implements hysteresis: enters Critical at `enter_threshold`, exits only when
    resources drop below `exit_threshold`. This prevents oscillation near the limit.
    """
    mem = psutil.virtual_memory()
    ram_percent = mem.percent
    
    vram_percent = -1.0
    try:
        # Attempt to pull NVIDIA VRAM 
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            encoding='utf-8',
            timeout=2
        ).strip().split('\n')[0]
        used, total = map(float, output.split(', '))
        if total > 0:
            vram_percent = (used / total) * 100
    except Exception:
        pass # Graceful fallback to ram_percent only
        
    # Hysteresis Logic:
    # 1. Decide if RAM/VRAM is "maxed" based on current status.
    if prev_status == "Critical":
        # Already critical: stay critical until we drop below exit threshold.
        vram_maxed = (vram_percent == -1.0) or (vram_percent >= exit_threshold)
        ram_maxed = (ram_percent >= exit_threshold)
    else:
        # Currently stable/warning: only enter critical if we hit enter threshold.
        vram_maxed = (vram_percent == -1.0) or (vram_percent >= enter_threshold)
        ram_maxed = (ram_percent >= enter_threshold)

    # AND-gate: Both components must be stressed to trigger Critical status.
    if ram_maxed and vram_maxed:
        status_level = "Critical"
    elif ram_percent >= 90.0:
        status_level = "Warning"
    else:
        status_level = "Stable"
        
    return {
        "status": status_level,
        "ram_percent": ram_percent,
        "vram_percent": vram_percent,
        "enter_threshold": enter_threshold,
        "exit_threshold": exit_threshold
    }
