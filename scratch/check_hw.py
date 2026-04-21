import psutil
import subprocess

def check():
    mem = psutil.virtual_memory()
    ram_percent = mem.percent
    print(f"RAM: {ram_percent}% ({mem.used/1024**3:.1f}GB / {mem.total/1024**3:.1f}GB)")
    
    vram_percent = -1.0
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            encoding='utf-8',
            timeout=2
        ).strip().split('\n')[0]
        used, total = map(float, output.split(', '))
        vram_percent = (used / total) * 100
        print(f"VRAM: {vram_percent:.1f}% ({used/1024:.1f}GB / {total/1024:.1f}GB)")
    except Exception as e:
        print(f"VRAM: Failed ({e})")

    vram_maxed = (vram_percent == -1.0) or (vram_percent >= 95.0)
    ram_maxed = (ram_percent >= 95.0)

    if ram_maxed and vram_maxed:
        print("STATUS: CRITICAL")
    elif ram_percent >= 90.0:
        print("STATUS: WARNING")
    else:
        print("STATUS: STABLE")

if __name__ == "__main__":
    check()
