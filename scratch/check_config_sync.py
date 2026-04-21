import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.identity import get_system_defaults
from core.tool_registry import ToolRegistry
from core.sentinel_logger import get_logger
from tools.system_config import _get_default_bounds
from tools.filesystem import _BLOCK_SIZE

def verify():
    print("--- Configuration Sync Verification ---")
    
    defaults = get_system_defaults()
    if not defaults:
        print("FAIL: system_defaults.json not found or empty")
        return

    # 1. Tool Registry
    reg = ToolRegistry()
    expected_cap = defaults.get("registry", {}).get("MAX_TOOL_OUTPUT")
    if reg.MAX_TOOL_OUTPUT == expected_cap:
        print(f"PASS: ToolRegistry.MAX_TOOL_OUTPUT ({reg.MAX_TOOL_OUTPUT})")
    else:
        print(f"FAIL: ToolRegistry.MAX_TOOL_OUTPUT ({reg.MAX_TOOL_OUTPUT} vs {expected_cap})")

    # 2. Filesystem
    expected_block = defaults.get("registry", {}).get("BLOCK_SIZE")
    if _BLOCK_SIZE == expected_block:
        print(f"PASS: filesystem._BLOCK_SIZE ({_BLOCK_SIZE})")
    else:
        print(f"FAIL: filesystem._BLOCK_SIZE ({_BLOCK_SIZE} vs {expected_block})")

    # 3. system_config tool
    bounds = _get_default_bounds()
    expected_temp = defaults.get("bounds", {}).get("temperature")
    if bounds.get("temperature") == expected_temp:
        print(f"PASS: system_config tool bounds ({bounds.get('temperature')})")
    else:
        print(f"FAIL: system_config tool bounds ({bounds.get('temperature')} vs {expected_temp})")

    # 4. History Compressor
    from core.history_compressor import _TRIGGER_MULTIPLIER
    expected_trigger = defaults.get("defaults", {}).get("history_compression_trigger")
    if _TRIGGER_MULTIPLIER == expected_trigger:
        print(f"PASS: history_compressor._TRIGGER_MULTIPLIER ({_TRIGGER_MULTIPLIER})")
    else:
        print(f"FAIL: history_compressor._TRIGGER_MULTIPLIER ({_TRIGGER_MULTIPLIER} vs {expected_trigger})")

    print("--- Verification Complete ---")

if __name__ == "__main__":
    verify()
