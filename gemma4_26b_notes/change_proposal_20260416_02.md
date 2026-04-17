# 🚀 Change Proposal: CP-20260416-02

**Title:** Unified Tool Metadata Schema Implementation
**Author:** [The Architect]
**Status:** Draft
**Date:** 2026-04-16

## 📋 Problem Statement
Currently, the `tool_registry.py` discovers tools based on file presence in the `tools/` directory. However, there is no standardized way to retrieve critical metadata (version, author, dependencies, or usage examples) without manually parsing docstrings or inspecting code. This lack of structure hinders:
1.  **The Analyst:** Difficulty in performing automated audits and risk assessments of tool updates.
2.  **The Orchestrator:** Inability to track the lifecycle and compatibility of tools within the `skill_map.md`.
3.  **The Sentinel:** Lack of visibility into tool-related resource consumption (e.g., identifying tools that heavily use VRAM).

## 🛠️ Proposed Solution
Implement a standardized metadata schema for all tools using a Python decorator approach. This schema will be parsed during the `INTEGRATE` phase of the cognitive loop.

### Key Components:
1.  **`@tool_metadata` Decorator:** A new decorator applied to every tool function in the `tools/` directory.
2.  **Schema Definition:**
    *   `version`: (string) Semantic version of the tool.
    *   `author`: (string) The role/user responsible for the tool.
    *   `dependencies`: (list) A list of other tools or system components required.
    *   `complexity_score`: (int 1-10) An estimate of the computational/resource cost.
    *   `usage_examples`: (list of strings) Structured input/output examples for the `Analyst` to use in testing.
3.  **Registry Update:** The `tool_registry.py` will be updated to extract this metadata and store it in the `state.db` (SQLite) for rapid querying.

## 📈 Expected Impact
- **Improved Observability:** `The Sentinel` can monitor high-complexity tools for resource spikes.
- **Enhanced Automation:** `The Orchestrator` can automatically update the `skill_map.md` with versioning and dependency info.
- **Robust Auditing:** `The Analyst` can use `usage_examples` to generate automated test suites for every tool in the registry.

## ⚠️ Risks & Mitigations
- **Risk:** Increased overhead during the `PERCEIVE`/`INTEGRATE` phase due to metadata parsing.
- **Mitigation:** Perform the parsing once during the `INTEGRATE` phase and cache the metadata in `state.db`.

--- 
*End of Proposal*