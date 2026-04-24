"""Phase D Step 7 -- full acceptance test for NN query + blended exploit.

Covers:
  A. Semantic hit
  B. Semantic miss
  C. Zero-vec row excluded from semantic
  D. None query -> exact-match fallback
  E. Wrong-dim query -> exact-match fallback
  F. All-zero query -> exact-match fallback
  G. lx_Reason._exploit blended ranking: close neighbour beats far high-R
  H. lx_Integrate reuses observation_embedding from state (no double-embed)
  I. lx_Observe emits observation_embedding when ollama is present
  J. Full chain OBSERVE->REASON wiring sanity check
"""
import sys, tempfile, shutil, math, os
sys.path.insert(0, "/sessions/charming-relaxed-gauss/mnt/ai")

from core.lx_state import lx_StateStore, _EMBED_DIM
from core import lx_cognates as lc

def unit(v):
    n = math.sqrt(sum(x*x for x in v))
    return [x/n for x in v] if n > 0 else v

tmp = tempfile.mkdtemp(prefix="lx_step7_full_")
store = lx_StateStore(profile="acc", state_dir=tmp)

# Anchors.
close_vec = [0.0] * _EMBED_DIM; close_vec[0] = 1.0; close_vec[1] = 0.05
close_vec = unit(close_vec)
far_vec = [0.0] * _EMBED_DIM; far_vec[1] = 1.0; far_vec[0] = 0.05
far_vec = unit(far_vec)

# Commit rows.
store.commit_success_vector("sig_close", "CLOSE_TOOL", 0.90, {"n":"c"}, close_vec)
store.commit_success_vector("sig_far",   "FAR_TOOL",   0.99, {"n":"f"}, far_vec)
# One zero-vec row (None embedding -> flagged "zero").
store.commit_success_vector("sig_zero", "ZERO_TOOL", 0.95, {"n":"z"}, None)
# Exact-match peer on sig_close for the fallback branches.
store.commit_success_vector("sig_close", "CLOSE_TOOL_EXACT", 0.88, {"n":"ce"},
                             close_vec)

print(f"rows committed: {store.count_success_vectors()}")

# Query near CLOSE.
query_vec = [0.7 * c + 0.3 * f for c, f in zip(close_vec, far_vec)]
query_vec = unit(query_vec)

# A. semantic hit.
a = store.query_success_vectors("sig_query", obs_embedding=query_vec,
                                limit=10, similarity_floor=0.5)
a_tools = sorted({m["tool_name"] for m in a})
assert a, "A: expected >=1 semantic hit"
assert "ZERO_TOOL" not in a_tools, f"A: zero-vec row leaked: {a_tools}"
print(f"A. semantic hit    tools={a_tools} n={len(a)}")

# B. semantic miss (pathological orthogonal vector, floor=0.999).
off_vec = [0.0] * _EMBED_DIM; off_vec[42] = 1.0
b = store.query_success_vectors("sig_query", obs_embedding=off_vec,
                                limit=10, similarity_floor=0.999)
assert b == [], f"B: expected empty, got {b}"
print(f"B. semantic miss   floor=0.999 -> {len(b)} rows")

# C. zero-vec row excluded even when similarity_floor is very low.
c = store.query_success_vectors("sig_query", obs_embedding=query_vec,
                                limit=50, similarity_floor=-1.0)
c_tools = {m["tool_name"] for m in c}
assert "ZERO_TOOL" not in c_tools, f"C: zero-vec row leaked: {c_tools}"
print(f"C. zero-vec excl   tools={sorted(c_tools)}")

# D. None -> exact-match.
d = store.query_success_vectors("sig_close", obs_embedding=None, limit=10)
d_tools = sorted({m["tool_name"] for m in d})
assert any("_similarity" not in m for m in d), "D: exact branch must omit _similarity"
assert "CLOSE_TOOL" in d_tools, f"D: exact-match missed: {d_tools}"
print(f"D. None -> exact   tools={d_tools} n={len(d)}")

# E. wrong-dim -> exact-match.
e = store.query_success_vectors("sig_close", obs_embedding=[0.1, 0.2, 0.3])
e_tools = sorted({m["tool_name"] for m in e})
assert any("_similarity" not in m for m in e)
assert "CLOSE_TOOL" in e_tools
print(f"E. bad dim -> exact tools={e_tools}")

# F. all-zero -> exact-match.
f = store.query_success_vectors("sig_close", obs_embedding=[0.0]*_EMBED_DIM)
f_tools = sorted({m["tool_name"] for m in f})
assert any("_similarity" not in m for m in f)
assert "CLOSE_TOOL" in f_tools
print(f"F. zero -> exact   tools={f_tools}")

# G. Blended exploit ranking via lx_Reason._exploit.
class _Stub:
    ollama = None
reason = lc.lx_Reason(_Stub())
# Force query vector very close to CLOSE anchor.
q_close = [0.97 * c + 0.03 * f for c, f in zip(close_vec, far_vec)]
q_close = unit(q_close)
tool, args = reason._exploit(store, "sig_query", q_close,
                             stderr_flag=False, last_tool=None)
print(f"G1. exploit near CLOSE -> {tool}")
assert tool in ("CLOSE_TOOL", "CLOSE_TOOL_EXACT"), f"G1: expected close-family winner, got {tool}"

# G2: query vector very close to FAR anchor -> FAR_TOOL should win.
q_far = [0.03 * c + 0.97 * f for c, f in zip(close_vec, far_vec)]
q_far = unit(q_far)
tool2, args2 = reason._exploit(store, "sig_query", q_far,
                               stderr_flag=False, last_tool=None)
print(f"G2. exploit near FAR   -> {tool2}")
assert tool2 == "FAR_TOOL", f"G2: expected FAR_TOOL, got {tool2}"

# G3: stderr recovery pivots away from last_tool.
tool3, args3 = reason._exploit(store, "sig_query", q_close,
                               stderr_flag=True, last_tool="CLOSE_TOOL")
print(f"G3. exploit stderr avoids CLOSE_TOOL -> {tool3}")
assert tool3 != "CLOSE_TOOL", f"G3: should have pivoted away, got {tool3}"

# H. lx_Integrate reuses observation_embedding.
# Feed a fake state with a non-None embedding; ensure Integrate commits with
# embed_source="ollama" rather than "zero".
class _FakeOllama:
    calls = 0
    def embed(self, text):
        _FakeOllama.calls += 1
        return [0.0] * _EMBED_DIM  # should NOT be called by Integrate now
class _Core:
    def __init__(self, store): self._active_store = store; self.ollama = _FakeOllama()

# Use a fresh store to keep commit sources clean.
tmp2 = tempfile.mkdtemp(prefix="lx_step7_h_")
store2 = lx_StateStore(profile="h", state_dir=tmp2)
core2 = _Core(store2)
integrate = lc.lx_Integrate(core2)
state_h = {
    "observation_signature": "sig_h",
    "observation_embedding": close_vec,     # reuse path
    "planned_tool": "file_list",
    "planned_args": {"path": "."},
    "last_outcome": {"tool_name": "file_list", "status": "ok", "return_value": "ok", "stderr": "", "latency_ms": 12.0},
    "reward": 0.85,
    "env_audit": {"fs_root": "/tmp"},
}
delta_h = integrate.execute(state_h)
print(f"H. integrate delta keys={list(delta_h.keys())} fake_embed_calls={_FakeOllama.calls}")
rows_h = store2._procedural_wins.get(where={"tool_name": "file_list"},
                                      include=["metadatas"])
metas_h = rows_h.get("metadatas") or []
assert any(m.get("embed_source") == "ollama" for m in metas_h), \
    f"H: Integrate should have reused real embedding; sources={[m.get('embed_source') for m in metas_h]}"
assert _FakeOllama.calls == 0, \
    f"H: Integrate must not call ollama.embed; called {_FakeOllama.calls}"
print("H. Integrate reused observation_embedding (no double-embed)")

# I. lx_Observe emits observation_embedding when ollama is present.
class _ObsOllama:
    def embed(self, text): return [0.5] * _EMBED_DIM
class _ObsCore:
    def __init__(self, store): self._active_store = store; self.ollama = _ObsOllama()
core3 = _ObsCore(lx_StateStore(profile="i", state_dir=tempfile.mkdtemp()))
observe = lc.lx_Observe(core3)
delta_i = observe.execute({"payload": "hello world"})
emb = delta_i.get("observation_embedding")
assert isinstance(emb, list) and len(emb) == _EMBED_DIM, \
    f"I: Observe must emit {_EMBED_DIM}-dim embedding; got {type(emb).__name__}"
print(f"I. Observe emits obs_embedding dim={len(emb)}")

# J. OBSERVE -> REASON wiring passes the embedding through.
# Reuse core3 with pre-seeded store, plus a reason on the same core.
reason3 = lc.lx_Reason(core3)
delta_r = reason3.execute(delta_i)
assert "planned_tool" in delta_r, f"J: Reason must produce planned_tool; got {delta_r}"
print(f"J. OBSERVE->REASON -> tool={delta_r['planned_tool']} mode={delta_r['decision_mode']}")

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp2, ignore_errors=True)
print("\nSTEP 7 ACCEPTANCE: ALL PASS")
