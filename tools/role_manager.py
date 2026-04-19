"""
role_manager — Enable, disable, and inspect agent roles.

Each role has one continuous goal. Enabling a role auto-creates its goal
in goals.json. Disabling a role removes the goal. This is the bridge
between the role identity system and the goal-driven execution loop.

Operations:
  - list:    Show all roles with enabled/disabled status
  - enable:  Activate a role (creates its continuous goal)
  - disable: Deactivate a role (removes its continuous goal)
  - sync:    Ensure all enabled roles have their goals in goals.json (startup repair)
"""

import json
import os
import time

TOOL_NAME        = "role_manager"
TOOL_DESCRIPTION = (
    "Manage agent roles. Each role has one continuous background task. "
    "Use 'list' to see all roles, 'enable <role>' to activate a role and its task, "
    "'disable <role>' to deactivate it, or 'sync' to repair goal state on startup."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "action": {
        "type": "string",
        "enum": ["list", "enable", "disable", "sync"],
        "description": "Action to perform.",
    },
    "role_name": {
        "type": "string",
        "description": "(For enable/disable) The role key: sentinel, analyst, architect, orchestrator, scholar, guardian. 'servo' is the default identity and is not schedulable.",
    },
}

_ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROLES_FILE = os.path.join(_ROOT, "roles.json")
_GOALS_FILE = os.path.join(_ROOT, "goals.json")

# Non-schedulable roles — identity overlays that never enter the goal queue.
# 'servo' is the default no-overlay identity and must never be elected as a
# due role (its schedule_minutes is 0 and its task is empty by design).
_NON_SCHEDULABLE = {"servo"}


def _is_schedulable(role_name: str, role: dict) -> bool:
    """A role is schedulable only if it's not in the deny-list, has a
    non-empty task, and has a positive schedule."""
    if role_name in _NON_SCHEDULABLE:
        return False
    if not (role.get("task") or "").strip():
        return False
    if int(role.get("schedule_minutes", 0)) <= 0:
        return False
    return True


def _load_roles() -> dict:
    if not os.path.exists(_ROLES_FILE):
        return {}
    try:
        with open(_ROLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_roles(roles: dict):
    with open(_ROLES_FILE, "w", encoding="utf-8") as f:
        json.dump(roles, f, indent=4)


def _load_goals() -> dict:
    if not os.path.exists(_GOALS_FILE):
        return {}
    try:
        with open(_GOALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_goals(goals: dict):
    with open(_GOALS_FILE, "w", encoding="utf-8") as f:
        json.dump(goals, f, indent=4)


def _goal_key(role_name: str) -> str:
    """Generate the goal name for a role, e.g. 'role_sentinel'."""
    return f"role_{role_name}"


def _create_goal_for_role(role_name: str, role: dict, goals: dict) -> dict:
    """Create a continuous goal for an enabled role."""
    key = _goal_key(role_name)
    goals[key] = {
        "type": "continuous",
        "description": f"[{role['title']}] {role['task']}",
        "schedule_minutes": role.get("schedule_minutes", 60),
        "last_run": time.time(),  # Don't fire immediately — let it wait one cycle
    }
    return goals


def _remove_goal_for_role(role_name: str, goals: dict) -> dict:
    """Remove the continuous goal for a disabled role."""
    key = _goal_key(role_name)
    goals.pop(key, None)
    return goals


def execute(action: str, role_name: str = "") -> str:
    roles = _load_roles()
    if not roles:
        return "Error: roles.json not found or empty."

    action = action.lower().strip()

    if action == "list":
        lines = ["AGENT ROLES:"]
        for key, role in roles.items():
            status = "✓ ENABLED" if role.get("enabled") else "  disabled"
            schedule = role.get("schedule_minutes", 60)
            lines.append(
                f"  [{status}] {role['title']} ({key}) — {role['domain']}"
                f"\n           Task: {role['task'][:100]}..."
                f"\n           Schedule: every {schedule}m"
            )
        return "\n".join(lines)

    if action == "sync":
        goals = _load_goals()
        synced = 0
        for key, role in roles.items():
            goal_key = _goal_key(key)
            # Non-schedulable roles (like servo) must never have a goal.
            # Prune any stale goal that was created before this guard existed.
            if not _is_schedulable(key, role):
                if goal_key in goals:
                    goals = _remove_goal_for_role(key, goals)
                    synced += 1
                continue
            if role.get("enabled") and goal_key not in goals:
                goals = _create_goal_for_role(key, role, goals)
                synced += 1
            elif not role.get("enabled") and goal_key in goals:
                goals = _remove_goal_for_role(key, goals)
                synced += 1
        _save_goals(goals)
        return f"Sync complete. {synced} goal(s) updated." if synced else "All roles already in sync."

    # enable / disable require a role_name
    if not role_name:
        return "Error: role_name is required for enable/disable."

    role_name = role_name.lower().strip()
    if role_name not in roles:
        valid = ", ".join(k for k in roles.keys() if k not in _NON_SCHEDULABLE)
        return f"Error: Unknown role '{role_name}'. Valid roles: {valid}"

    if role_name in _NON_SCHEDULABLE:
        return (
            f"Error: '{role_name}' is a non-schedulable identity overlay, not a task-driven role. "
            "It is always available as the default voice and cannot be enabled or disabled."
        )

    role = roles[role_name]
    goals = _load_goals()

    if action == "enable":
        if role.get("enabled"):
            return f"{role['title']} is already enabled."

        role["enabled"] = True
        roles[role_name] = role
        _save_roles(roles)

        goals = _create_goal_for_role(role_name, role, goals)
        _save_goals(goals)

        return f"✓ {role['title']} enabled. Continuous goal '{_goal_key(role_name)}' created (every {role.get('schedule_minutes', 60)}m)."

    elif action == "disable":
        if not role.get("enabled"):
            return f"{role['title']} is already disabled."

        role["enabled"] = False
        roles[role_name] = role
        _save_roles(roles)

        goals = _remove_goal_for_role(role_name, goals)
        _save_goals(goals)

        return f"✗ {role['title']} disabled. Goal '{_goal_key(role_name)}' removed."

    return f"Error: Unknown action '{action}'. Use list, enable, disable, or sync."
