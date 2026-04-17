# Architecture Review - Servo - Cybernetic Actuator

**Last Updated:** January 15, 2025
**Review Cycle:** Continuous (every 120 minutes)

---

## ✅ Strengths

1. **Clean separation of concerns** - Core loop, state, tools, and client are well-isolated
2. **Dynamic tool loading** - Can add/modify tools at runtime without restart
3. **Persistent memory** - Both SQLite (structured) and ChromaDB (vector) for different use cases
4. **Auto-chaining** - Tool calls can chain up to 3 iterations automatically
5. **Streaming support** - Real-time response streaming available
6. **Tool call parsing** - Multiple fallback strategies for JSON extraction

---

## ⚠️ CRITICAL Security Issues

### 1. **Shell Command Injection**
**Location:** `tools/shell_exec.py`
**Code:** `subprocess.run(command, shell=True, ...)`
**Risk:** **CRITICAL** - Allows arbitrary command execution
- User input can inject malicious commands
- Example: `rm -rf /` or reverse shell attacks
- Even with timeout, the damage is done

**Fix Required:**
```python
# DON'T use shell=True
result = subprocess.run(
    ["cmd.exe", "/C", command],  # Split into list
    capture_output=True,
    text=True,
    timeout=timeout,
)

# OR implement command whitelisting:
ALLOWED_COMMANDS = ["dir", "ls", "ping", "echo", "type", "cat", "python", "pytest", "npm", "npx", "git"]
for cmd in ALLOWED_COMMANDS:
    if cmd in command:
        # sanitize and allow
        break
else:
    raise PermissionError("Command not allowed")
```

**Status:** ✅ **FIXED** - Command whitelist now implemented (restricted to: dir, ls, ping, echo, type, cat, python, pytest, npm, npx, git)

### 2. **Filesystem Path Traversal**
**Location:** `tools/filesystem.py`
**Code:** `p = Path(path)` - no validation
**Risk:** **HIGH** - Can read/write anywhere on disk
- `../../etc/passwd` can read system files
- Can overwrite critical files
- Can delete important data

**Fix Required:**
```python
import os
from pathlib import Path

# Normalize and validate path
path = Path(path).resolve()
allowed_base = Path("C:/Users/kevin/OneDrive/Desktop/ai/qwen3_5_27b_notes").resolve()

if not str(path).startswith(str(allowed_base)):
    raise PermissionError("Access denied: path outside allowed directory")
```

**Status:** ✅ **FIXED** - Sandbox policy now enforced - all writes restricted to notes folder

### 3. **Database Concurrency Issues**
**Location:** `core/state.py`
**Code:** `check_same_thread=False`
**Risk:** **MEDIUM** - Race conditions possible
- Multiple writes could corrupt state
- No transaction management
- WAL mode not enabled

**Fix Required:**
```python
# Enable WAL mode
self.conn.execute("PRAGMA journal_mode=WAL")

# Use transactions for related operations
with self.conn:
    self.conn.execute("INSERT INTO ...")
    self.conn.execute("INSERT INTO ...")
```

**Status:** ⚠️ **PENDING** - Should implement WAL mode and transaction wrapping

### 4. **Memory Growth Without Limits**
**Location:** `core/state.py` - ChromaDB
**Risk:** **MEDIUM** - Vector DB grows indefinitely
- No pruning or cleanup strategy
- Could exhaust disk space
- Slow query performance over time

**Fix Required:**
```python
# Add memory pruning
MAX_MEMORY_SIZE = 100  # MB

def prune_memory(self):
    # Delete oldest entries when size exceeds limit
    total_size = self.memory_collection.count()
    if total_size > MAX_MEMORY_SIZE:
        # Delete oldest entries
        self.memory_collection.delete(
            where={"timestamp": {"$lt": self.get_oldest_timestamp()}}
        )
```

**Status:** ⚠️ **PENDING** - Should implement memory pruning

---

## 📋 Priority Actions

| Priority | Issue | Impact | Effort | Status |
|------|-------|--------|--------|--------|
| **P0** | Shell command injection | **CRITICAL** | Medium | ✅ Fixed |
| **P0** | Filesystem path traversal | **HIGH** | Medium | ✅ Fixed |
| **P1** | Memory growth limits | Medium | Low | ⚠️ Pending |
| **P1** | Database concurrency | Medium | Medium | ⚠️ Pending |
| **P2** | Error handling/retry | Medium | Low | ⚠️ Pending |
| **P3** | Tool call parsing | Low | Medium | ⚠️ Pending |
| **P3** | Dynamic Model Manager (Optional) | Low | Medium | ℹ️ Deferred |

---

## 🔧 Immediate Fixes Needed

1. **Enable WAL mode** - Better SQLite concurrency handling
2. **Add memory pruning** - Implement cleanup for ChromaDB
3. **Add retry logic** - For OllamaClient and tool calls
4. **Improve error handling** - Add circuit breaker for repeated failures

---

*Part 1 of 2 - Architecture Review*
