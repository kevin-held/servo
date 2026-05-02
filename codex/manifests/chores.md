# Servo — Surgical Initialization Chores

You are starting a new session. Your priority is to establish absolute source-code familiarity and synchronize your internal state with the current project architecture, the resident memory, and the operator's intent.

### Prerequisite: 
A. The automatically injected startup prompt indicates 100% of tests pass. 80% test coverage minimum. If not, report to user with no tool call to stop the loop. Good Test results must be followed by the next step.
B. use `log_query` tool to query the logs if you find any errors, report them to the user with no tool call to stop the loop. Clean logs must be followed by the next step.
C. Use the `task` tool to register this entire 6-step sequence up front. Use the batch schema: `action="create"` and pass the following exact JSON array into the `tasks` parameter:
```json
[
  "1. use map_project tool on the root ",
  "2. use the file_write tool to save workspace/architecture_review_YYYYMMDD_HHMMSS.md",
  "3. use memory_manager tool to overwrite the current working memory entry",
  "4. use log_query tool to query the logs for any errors or warnings",
  "5. use task tool (action='list') and resolve remaining tasks",
  "6. use task tool (action='complete') to mark this chore list as complete"
]
```
Once the ledger is created, execute the following 6 items one by one, calling `task(action="complete", task_id=X)` as you finish each:



### Chat Output Directive
For every step below, you must write a conversational summary of your intended action **as plain text first**. The core Loop isolates any text written outside a tool call and routes it to the operator's chat window. Do not put the summary inside the tool arguments. Write your prose, then make the tool call.

### Directive 1: Source Code Synchronization
1. Write a plain-text summary to the chat, then use the `map_project` tool on the root directory.


### Directive 2: Architectural Persistence
2. Synthesize the structural findings from Directive 1. Write a plain-text summary to the chat explaining your findings, then use the `file_write` tool to save `workspace/architecture_review_YYYYMMDD_HHMMSS.md`. This ensures your structural understanding is persisted outside of the transient context window for future turns.

### Directive 3: Working Memory Synthesis
3. Write a plain-text chat summary, then use `memory_manager` to overwrite the current working memory entry with recent changes, operational context, current objectives, and immediate constraints specific to the active session. Do maintain artifacts that are relevant to the current session, or provide additional safeguards that help you avoid repeating mistakes, especially ones related to fixed internal training weights that may be outdated or need tailoring per the user's request. Avoid maintaining knowledge that is already codified in your system prompts or if it is reliably triggered by recent memory injection. Include specific details from `codex/manifests/persona_core.md` and other relevant manifests like `servo_lexicon.md`, `servo_glossary.md`, etc.

### Directive 4: Log Audit
4. Write a plain-text chat summary, then use `log_query` to check the logs for any errors or warnings that may have occurred during chores. Report significant findings to the operator.


With no log issues and no remaining tasks, signal "Servo Ready" to the operator.