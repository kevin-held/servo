import sqlite3
import json
import os
import sys
import time

# We need to access state.db, which is usually abstracted by StateStore.
# The tool executor doesn't pass StateStore in automatically, so we'll 
# manually read/write to the state sqlite db if needed, OR we can just 
# maintain a goals.json file in the workspace sandbox for ultra-reliability.
# Let's use goals.json in the workspace root for simplicity and persistence.

TOOL_NAME        = "goal_manager"
TOOL_DESCRIPTION = "Manage autonomous goals. Priority 1 goes to 'finite' goals (with clear criteria to be marked complete). Priority 2 goes to 'continuous' (never-ending maintenance). Always complete a finite goal when its criteria are successfully met."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "action": {"type": "string", "enum": ["add", "remove", "complete", "list", "mark_run", "update_schedule"], "description": "The action to perform"},
    "goal_name": {"type": "string", "description": "A short unique name for the goal (e.g. 'compile_code') - not needed for 'list' action"},
    "goal_type": {"type": "string", "enum": ["finite", "continuous"], "description": "Required for 'add': is it a finite task or continuous background task?"},
    "description": {"type": "string", "description": "Required for 'add' or 'update_schedule'(optional): clear instructions on what needs to be achieved."},
    "schedule_minutes": {"type": "integer", "description": "For continuous goals: how often they should run (default 60). Used in 'add' or 'update_schedule'."},
    "duration_minutes": {"type": "integer", "description": "For finite goals only (optional): auto-expire this goal after N minutes. Use this when told to 'do X for 30 minutes'."}
}

GOALS_FILE = os.path.join(os.path.dirname(__file__), "..", "goals.json")

def _load_goals() -> dict:
    if not os.path.exists(GOALS_FILE):
        return {}
    try:
        with open(GOALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_goals(goals: dict):
    with open(GOALS_FILE, "w", encoding="utf-8") as f:
        json.dump(goals, f, indent=4)

def execute(action: str, goal_name: str = "", goal_type: str = "", description: str = "", schedule_minutes: int = 60, duration_minutes: int = 0) -> str:
    action = action.lower()
    goals = _load_goals()
    
    if action == "list":
        if not goals:
            return "No active goals."
        out = "ACTIVE GOALS:\n"
        # Return finite first, then continuous
        for t in ["finite", "continuous"]:
            for name, meta in goals.items():
                if meta.get("type") == t:
                    desc = meta.get('description')
                    if t == "continuous":
                        sched = meta.get("schedule_minutes", 60)
                        last_run = meta.get("last_run", 0)
                        min_ago = int((time.time() - last_run)/60)
                        out += f"- [{t.upper()}] {name}: {desc} (Schedule: every {sched}m, Last run: {min_ago}m ago)\n"
                    else:
                        expires_at = meta.get("expires_at")
                        if expires_at:
                            remaining = max(0, int((expires_at - time.time()) / 60))
                            out += f"- [FINITE] {name}: {desc} (Auto-expires in {remaining} min)\n"
                        else:
                            out += f"- [FINITE] {name}: {desc}\n"
        return out.strip()
        
    if not goal_name:
        return "Error: goal_name is required for this action."
        
    goal_name = goal_name.replace(" ", "_").lower()

    if action == "add":
        if not goal_type or not description:
            return "Error: goal_type and description are required to add a goal."
        if goal_type not in ["finite", "continuous"]:
            return "Error: goal_type must be 'finite' or 'continuous'."
            
        goals[goal_name] = {"type": goal_type, "description": description}
        if goal_type == "continuous":
            goals[goal_name]["schedule_minutes"] = schedule_minutes
            goals[goal_name]["last_run"] = time.time() - (schedule_minutes * 60) # Due immediately
        elif goal_type == "finite" and duration_minutes > 0:
            goals[goal_name]["expires_at"] = time.time() + (duration_minutes * 60)
            
        _save_goals(goals)
        return f"Successfully added {goal_type} goal: {goal_name}" + (
            f" (auto-expires in {duration_minutes} minutes)" if goal_type == "finite" and duration_minutes > 0 else ""
        )
        
    elif action == "remove":
        if goal_name in goals:
            del goals[goal_name]
            _save_goals(goals)
            return f"Successfully removed goal: {goal_name}"
        return f"Error: Goal '{goal_name}' not found."
        
    elif action == "mark_run":
        if goal_name in goals:
            if goals[goal_name]["type"] != "continuous":
                return f"Error: '{goal_name}' is not a continuous goal."
            goals[goal_name]["last_run"] = time.time()
            _save_goals(goals)
            return f"Successfully snoozed continuous goal: {goal_name}"
        return f"Error: Goal '{goal_name}' not found."
        
    elif action == "update_schedule":
        if goal_name in goals:
            if goals[goal_name]["type"] != "continuous":
                return f"Error: '{goal_name}' is not a continuous goal."
            goals[goal_name]["schedule_minutes"] = schedule_minutes
            if description:
                goals[goal_name]["description"] = description
            _save_goals(goals)
            return f"Successfully updated schedule for: {goal_name} to every {schedule_minutes} minutes."
        return f"Error: Goal '{goal_name}' not found."
        
    elif action == "complete":
        if goal_name in goals:
            meta = goals[goal_name]
            if meta["type"] == "continuous":
                return f"Error: '{goal_name}' is a continuous maintenance goal and cannot be 'completed'. You must 'remove' it if it is no longer needed."
            
            del goals[goal_name]
            _save_goals(goals)
            return f"SUCCESS: Goal '{goal_name}' marked as securely COMPLETED! Proceeding to next objective."
        return f"Error: Goal '{goal_name}' not found."

    return "Error: Invalid action."
