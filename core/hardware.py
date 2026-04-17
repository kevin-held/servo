import psutil
import subprocess

def get_resource_status() -> dict:
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
        
    status_level = "Stable"
    # Allow Ollama to safely pull heavily from Windows Shared GPU Memory.
    # Only fire Critical mitigation when BOTH VRAM and sys RAM are actively maxed out.
    vram_maxed = (vram_percent == -1.0) or (vram_percent >= 95.0)
    ram_maxed = (ram_percent >= 95.0)

    if ram_maxed and vram_maxed:
        status_level = "Critical"
    elif ram_percent >= 90.0:
        status_level = "Warning"
        
    return {
        "status": status_level,
        "ram_percent": ram_percent,
        "vram_percent": vram_percent
    }
