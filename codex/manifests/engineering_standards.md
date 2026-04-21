# Engineering Standards

**Version:** 1.3
**Status:** In-Effect

These standards are non-negotiable and must be applied by all roles during execution. Failure to adhere to these principles constitutes a critical state regression.

## 1. Code Standards

### Python
*   **Safety first:** Ensure all filesystem operations are confined to the sandbox (authorized: `workspace/`, `codex/manifests/`, and `configs/` for system parameters).
*   **Error Handling:** Wrap external API calls (Ollama, ChromaDB) in try/except blocks to prevent loop crashes.

### UI / CSS
*   **Rich Aesthetics:** Use HSL colors, CSS variables, and modern typography (Google Fonts) as per the *Aesthetic Mandate*.
*   **Visual Excellence:** Prioritize premium visual presentation. Avoid generic styles.

## 2. Documentation Standards

### Path Discipline
*   **Absolute Paths are forbidden** (D-20260417-09). Always use project-root-relative paths (e.g., `codex/manifests/lexicon.md`) to ensure portability across different host environments.
*   **Self-Correction:** If you detect an absolute path in your context or reasoning, immediately convert it to a relative path before acting.

### Alerts & Feedback
*   Use GitHub-style Alerts (`> [!IMPORTANT]`, `> [!WARNING]`) in reports and plans to highlight critical architectural breakpoints.

**Truncation Awareness**
*   Respect the 16,000 character tool output cap. use the optional block 1 argument with compatible tools like a filesystem read or youtube_transcript to get the next block.

---
*Maintained by The Architect*
