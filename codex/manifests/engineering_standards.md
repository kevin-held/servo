# Engineering Standards

**Version:** 1.4
**Status:** In-Effect

These standards are non-negotiable and must be applied by all roles during execution. Failure to adhere to these principles constitutes a critical state regression.

## 1. Code Standards

### Python
*   **Safety first:** Ensure all filesystem operations are confined to the sandbox (authorized: `workspace/`, `codex/manifests/`, and `configs/` for system parameters).
*   **Error Handling:** Wrap external API calls (Ollama, ChromaDB) in try/except blocks to prevent loop crashes.
*   **Registry-First:** All system parameters and safety scalars must be resolved via the `ConfigRegistry` to honor the Tiered Resolution protocol (Env > State > Default). Direct `StateStore.get()` for configuration is legacy.
*   **Test Isolation (D-20260421-10):** All unit tests involving the filesystem or database must use `tempfile.TemporaryDirectory` or unique test-prefixes to prevent "Cortex Corruption" of the production environment.

### Naming Fitness
*   **Variable Names:** If a name requires a comment to explain its purpose, it has "low fitness." A "high fitness" name is the shortest possible string that eliminates the need for an explanation.

### UI / CSS
*   **Rich Aesthetics:** Use HSL colors, CSS variables, and modern typography (Google Fonts) as per the *Aesthetic Mandate*.
*   **Visual Excellence:** Prioritize premium visual presentation. Avoid generic styles.
*   **Profile Feedback:** When running non-default state profiles, the GUI must clearly display the active profile name in the title bar.

## 2. Documentation Standards

### Path Discipline
*   **Absolute Paths are forbidden** (D-20260417-09). Always use project-root-relative paths (e.g., `codex/manifests/lexicon.md`) to ensure portability across different host environments.
*   **Self-Correction:** If you detect an absolute path in your context or reasoning, immediately convert it to a relative path before acting.

### Alerts & Feedback
*   Use GitHub-style Alerts (`> [!IMPORTANT]`, `> [!WARNING]`) in reports and plans to highlight critical architectural breakpoints.

*   Respect the `MAX_TOOL_OUTPUT` registry cap. Use the optional block arguments or line-range parameters (`start_line`/`end_line`) to paginate or surgically retrieve results.

**Efficient File Investigative Pattern**
*   **Precision over Volume:** When investigating specific code sections, prioritize `file_read` with `start_line`/`end_line` to conserve context altitude and improve reasoning focus. Use `map_project` first to identify the relevant ranges.

---
*Maintained by The Architect*
