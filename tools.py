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
        "name": "get_team_prs",
        "description": "Get all open PRs from specific authors across specific repositories. Useful for tracking feature team work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "authors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of GitHub usernames to track",
                },
                "repos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of repositories in owner/name format",
                },
            },
            "required": ["authors", "repos"],
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


def get_team_prs(authors: List[str], repos: List[str]) -> Dict[str, Any]:
    """Get all open PRs from specific authors across specific repositories."""
    all_prs = []

    # gh search doesn't work well with complex queries, so we iterate per repo
    for repo in repos:
        for author in authors:
            cmd = [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--author",
                author,
                "--state",
                "open",
                "--json",
                "number,title,url,author,isDraft,createdAt,reviewDecision,statusCheckRollup,labels,state,body,headRefOid",
                "--limit",
                "50",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # Skip repos that don't exist or we can't access
                continue

            repo_prs = json.loads(result.stdout)
            # Add repo info to each PR since it's not included in the JSON
            # Also summarize statusCheckRollup to reduce token usage
            for pr in repo_prs:
                pr["repository"] = repo

                # Extract tide status with description if available
                # Tide has all the merge rules, required jobs and context for proper status
                tide_status = None
                rollup = pr.get("statusCheckRollup", [])
                if rollup:
                    # Look for tide status in the rollup
                    for check in rollup:
                        if check.get("context") == "tide":
                            # Fetch the detailed tide status from the API to get description
                            head_sha = pr.get("headRefOid")
                            if head_sha:
                                api_cmd = [
                                    "gh", "api",
                                    f"repos/{repo}/commits/{head_sha}/status",
                                    "--jq", '.statuses[] | select(.context == "tide") | {state: .state, description: .description}'
                                ]
                                api_result = subprocess.run(api_cmd, capture_output=True, text=True)
                                if api_result.returncode == 0 and api_result.stdout.strip():
                                    tide_data = json.loads(api_result.stdout)
                                    tide_status = {
                                        "state": tide_data.get("state", "unknown").upper(),
                                        "description": tide_data.get("description", "")
                                    }
                            break

                pr["tideStatus"] = tide_status
                # Remove the full rollup to save tokens
                pr.pop("statusCheckRollup", None)
                pr.pop("headRefOid", None)  # Don't need this in the final output
            all_prs.extend(repo_prs)

    # Filter to ensure only OPEN PRs (not MERGED or CLOSED) and deduplicate
    seen = set()
    open_prs = []
    for pr in all_prs:
        # Skip merged or closed PRs
        if pr.get("state", "").upper() in ["MERGED", "CLOSED"]:
            continue

        pr_id = (pr["repository"], pr["number"])
        if pr_id not in seen:
            seen.add(pr_id)
            open_prs.append(pr)

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
    "get_team_prs": get_team_prs,
    "get_pr_details": get_pr_details,
    "add_pr_label": add_pr_label,
    "get_previous_state": get_previous_state,
    "save_state": save_state,
}


def check_library_go_rebase_status(repos: List[str]) -> Dict[str, Any]:
    """Check if operator repos are rebased against library-go HEAD.

    Args:
        repos: List of repo names in format "openshift/repo-name"

    Returns:
        Dict with repo status: {
            "library_go_sha": "abc123...",
            "library_go_short_sha": "abc123",
            "repos": {
                "openshift/repo-name": {
                    "is_rebased": bool,
                    "current_sha": "def456...",
                    "current_short_sha": "def456"
                }
            }
        }
    """
    # Get library-go HEAD SHA (uses master branch)
    cmd = ["gh", "api", "repos/openshift/library-go/branches/master", "--jq", ".commit.sha"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": f"Failed to get library-go HEAD: {result.stderr}"}

    library_go_sha = result.stdout.strip()
    library_go_short = library_go_sha[:7]

    repo_status = {}
    for repo in repos:
        # Get go.mod from repo
        repo_name = repo.split("/")[-1]
        cmd = ["gh", "api", f"repos/{repo}/contents/go.mod", "--jq", ".content"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            repo_status[repo] = {
                "is_rebased": False,
                "current_sha": None,
                "current_short_sha": None,
                "error": "Could not fetch go.mod"
            }
            continue

        # Decode base64 content
        import base64
        go_mod_content = base64.b64decode(result.stdout.strip()).decode('utf-8')

        # Parse library-go version from go.mod
        # Look for line like: github.com/openshift/library-go v0.0.0-20240101000000-abc123def456
        # The SHA is the last part after the last hyphen, but it's only 12 chars
        # We need to compare it with the first 12 chars of library-go HEAD
        current_sha = None
        for line in go_mod_content.split('\n'):
            if 'github.com/openshift/library-go' in line and not line.strip().startswith('//'):
                # Extract SHA from version string (last part after -)
                parts = line.split()
                if len(parts) >= 2:
                    version = parts[1]
                    if '-' in version:
                        # The version format is v0.0.0-YYYYMMDDHHMMSS-abcdef123456
                        # The SHA is the last 12 characters
                        current_sha = version.split('-')[-1]
                        break

        if current_sha:
            # go.mod only stores first 12 chars of SHA, so compare with library-go's first 12
            is_rebased = current_sha == library_go_sha[:12]
            repo_status[repo] = {
                "is_rebased": is_rebased,
                "current_sha": current_sha,
                "current_short_sha": current_sha[:7]
            }
        else:
            repo_status[repo] = {
                "is_rebased": False,
                "current_sha": None,
                "current_short_sha": None,
                "error": "Could not parse library-go version from go.mod"
            }

    return {
        "library_go_sha": library_go_sha,
        "library_go_short_sha": library_go_short,
        "repos": repo_status
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
