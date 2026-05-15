"""GitHub tools using gh CLI."""

import json
import subprocess
from typing import Any, Dict, List

# Tool definitions for Claude
GITHUB_TOOLS = [
    {
        "name": "get_my_prs",
        "description": "List all PRs created by the user across all repositories. Returns PR number, title, status, review status, and repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Filter by PR state (default: open)",
                }
            },
        },
    },
    {
        "name": "get_prs_needing_review",
        "description": "List all PRs where the user is requested as a reviewer but hasn't reviewed yet.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pr_details",
        "description": "Get detailed information about a specific PR including review status, checks, and comments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format (e.g., 'facebook/react')",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "PR number",
                },
            },
            "required": ["repo", "pr_number"],
        },
    },
    {
        "name": "add_pr_label",
        "description": "Add a label to a PR. Common labels: 'urgent', 'needs-review', 'blocked', 'ready-to-merge'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "PR number",
                },
                "label": {
                    "type": "string",
                    "description": "Label to add",
                },
            },
            "required": ["repo", "pr_number", "label"],
        },
    },
    {
        "name": "get_previous_state",
        "description": "Load the state from the previous run to detect what's changed. Returns last seen PRs, tickets, and the previous brief.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_state",
        "description": "Save the current state for the next run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "object",
                    "description": "State to save (PRs, tickets, brief summary)",
                }
            },
            "required": ["state"],
        },
    },
]


def get_my_prs(state: str = "open") -> Dict[str, Any]:
    """Use gh CLI to get user's PRs across all repositories."""
    cmd = [
        "gh",
        "search",
        "prs",
        "--author",
        "@me",
        "--state",
        state,
        "--json",
        "number,title,url,repository,author,labels,isDraft,updatedAt,createdAt,state",
        "--limit",
        "100",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr}

    all_prs = json.loads(result.stdout)
    # If state is "open", filter to ensure we only get OPEN PRs
    if state == "open":
        filtered_prs = [pr for pr in all_prs if pr.get("state", "").upper() == "OPEN"]
        return {"prs": filtered_prs}
    return {"prs": all_prs}


def get_prs_needing_review() -> Dict[str, Any]:
    """Get PRs where user is requested as reviewer."""
    cmd = [
        "gh",
        "search",
        "prs",
        "--review-requested",
        "@me",
        "--state",
        "open",
        "--json",
        "number,title,url,repository,author,labels,state,updatedAt",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr}

    # Explicitly filter out merged/closed PRs (gh CLI sometimes returns them despite --state open)
    all_prs = json.loads(result.stdout)
    open_prs = [pr for pr in all_prs if pr.get("state", "").upper() == "OPEN"]
    return {"prs": open_prs}


def get_pr_details(repo: str, pr_number: int) -> Dict[str, Any]:
    """Get detailed PR information."""
    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "number,title,body,state,reviewDecision,reviews,statusCheckRollup,comments",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr}
    return json.loads(result.stdout)


def add_pr_label(repo: str, pr_number: int, label: str) -> Dict[str, Any]:
    """Add label to PR."""
    cmd = ["gh", "pr", "edit", str(pr_number), "--repo", repo, "--add-label", label]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr}
    return {"success": True, "message": f"Added label '{label}' to PR #{pr_number}"}


def get_previous_state(state_file: str = "briefings/state.json") -> Dict[str, Any]:
    """Load previous state."""
    try:
        with open(state_file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"prs": {}, "tickets": {}, "last_run": None, "briefs": []}


def save_state(state: Dict[str, Any], state_file: str = "briefings/state.json") -> Dict[str, Any]:
    """Save current state."""
    # Create briefings directory if it doesn't exist
    import os
    state_dir = os.path.dirname(state_file)
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)

    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    return {"success": True}


# Map tool names to implementations
TOOL_IMPLEMENTATIONS = {
    "get_my_prs": get_my_prs,
    "get_prs_needing_review": get_prs_needing_review,
    "get_pr_details": get_pr_details,
    "add_pr_label": add_pr_label,
    "get_previous_state": get_previous_state,
    "save_state": save_state,
}


def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool and return the result."""
    func = TOOL_IMPLEMENTATIONS.get(tool_name)
    if not func:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return func(**tool_input)
    except Exception as e:
        return {"error": str(e)}
