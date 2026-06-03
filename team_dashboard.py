#!/usr/bin/env python3
"""Feature team PR dashboard with LLM filtering - outputs markdown directly."""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from anthropic import AnthropicVertex
from dotenv import load_dotenv
from tools import get_team_prs

# Load environment variables
load_dotenv()

# KMS team configuration
KMS_TEAM = {
    "name": "KMS",
    "authors": [
        "bertinatto",
        "ardaguclu",
        "gangwgr",
        "p0lyn0mial",
        "tjungblu",
        "ibihim",
        "flavianmissi",
    ],
    "repos": [
        "openshift/library-go",
        "openshift/enhancements",
        "openshift/cluster-kube-apiserver-operator",
        "openshift/cluster-openshift-apiserver-operator",
        "openshift/api",
        "openshift/cluster-authentication-operator",
    ],
}

FILTER_SYSTEM_PROMPT = """You are a PR dashboard generator for the KMS/Vault/encryption feature team.

PRs have already been filtered to only KMS-related work. Your job is to format them into a clear dashboard.

**CRITICAL: PR References**
- ALWAYS use full repo format: openshift/repo#number (e.g., openshift/library-go#2264)
- NEVER use just #number (it will resolve to wrong repo in GitHub issue)
- In action items: "Missing /lgtm on openshift/enhancements#2005"
- In tables, the "PR" column should be: [openshift/repo#number](url)

**Action items:**
- List ALL missing conditions in order for each PR
- Format: "Missing /lgtm, /approve on openshift/repo#number (short title)"
- ONLY reference PRs shown in their table
- NO generic advice

**Status Format:**
List ALL missing items comma-separated:
- "Missing /lgtm" (if has_lgtm is false)
- "Missing /approve" (if has_approved is false)
- "Missing /verified" (if has_verified is false AND is_enhancements_repo is false)
- "CI Failing" (if ci_status is FAILING)
If nothing missing: "Ready to Merge"

**Output Format:**

# KMS Team PR Dashboard
**Generated:** {timestamp}

## Summary
- Relevant PRs: X
- Ready to Merge: X
- Needs Action: X

---

## {Person Name} (@username)

**Action Items:**
- Missing /lgtm, /approve on openshift/library-go#123 (title)
- Missing /verified on openshift/api#456 (title)

| Repo | PR | Title | Status | Priority | Days |
|------|-----|-------|--------|----------|------|
| repo-short | [openshift/repo#123](url) | title | Missing /lgtm, /approve | 🔴 high | X |

**Priority:** 🔴 high = <7d, 🟡 medium = 7-30d, 🟢 low = >30d

Sort people by PR count (most first).
"""


def short_repo_name(repo: str) -> str:
    """Convert openshift/library-go to library-go."""
    return repo.split("/")[-1]


def days_since(iso_timestamp: str) -> int:
    """Calculate days since a timestamp."""
    created = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - created).days


def get_status_string(pr: Dict[str, Any]) -> str:
    """Get status string for a PR."""
    labels = [label.get("name", "") for label in pr.get("labels", [])]
    has_lgtm = "lgtm" in labels
    has_approved = "approved" in labels
    do_not_merge_wip = "do-not-merge/work-in-progress" in labels
    repo = pr.get("repository", "")

    # Tide verify label check (skip for enhancements repo)
    if "enhancements" not in repo:
        if not any(label.startswith("verified") or label == "verified" for label in labels):
            return "Needs /verified"

    # Draft or WIP
    if pr.get("isDraft") or do_not_merge_wip:
        return "Draft/WIP"

    # CI status check
    if pr.get("ciStatus") == "FAILING":
        return "CI Failing"

    # Approval check
    if not has_lgtm and not has_approved:
        if pr.get("reviewDecision") == "CHANGES_REQUESTED":
            return "Changes Requested"
        return "Needs /lgtm or /approve"

    # If approved but CI not passing
    if pr.get("ciStatus") != "PASSING":
        return "Waiting for CI"

    return "Ready to Merge"


def filter_prs(all_prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter PRs to only KMS-related work, removing noise."""
    filtered = []

    # Keywords that must be in title OR body (case insensitive)
    INCLUDE_KEYWORDS = ["kms", "vault", "encryption", "key", "rotation", "preflight", "kek", "keyId"]

    # Patterns to exclude (case insensitive)
    EXCLUDE_PATTERNS = ["wip", "[wip]", "do not merge", "dnm", "fake bump", "testing ote"]

    for pr in all_prs:
        title_lower = pr["title"].lower()
        body_lower = pr.get("body", "").lower() if pr.get("body") else ""

        # Skip if draft
        if pr.get("isDraft", False):
            continue

        # Skip if has exclude pattern in title
        if any(pattern in title_lower for pattern in EXCLUDE_PATTERNS):
            continue

        # Include if has KMS-related keyword in title OR body
        has_keyword_in_title = any(keyword in title_lower for keyword in INCLUDE_KEYWORDS)
        has_keyword_in_body = any(keyword in body_lower for keyword in INCLUDE_KEYWORDS)

        if has_keyword_in_title or has_keyword_in_body:
            filtered.append(pr)

    return filtered


async def generate_dashboard(all_prs: List[Dict[str, Any]]) -> str:
    """Use LLM to generate filtered dashboard as markdown."""
    client = AnthropicVertex(
        region=os.getenv("ANTHROPIC_VERTEX_REGION", "us-east5"),
        project_id=os.getenv("ANTHROPIC_VERTEX_PROJECT_ID"),
    )

    # Filter PRs deterministically in Python first
    filtered_prs = filter_prs(all_prs)

    print(f"Filtered to {len(filtered_prs)} KMS-related PRs (from {len(all_prs)} total)")

    # Prepare PR data for LLM
    pr_data = []
    for pr in filtered_prs:
        labels = [label.get("name", "") for label in pr.get("labels", [])]
        pr_data.append({
            "repo_short": short_repo_name(pr["repository"]),
            "repo_full": pr["repository"],
            "number": pr["number"],
            "url": pr["url"],
            "title": pr["title"],
            "author": pr["author"]["login"],
            "author_name": pr["author"].get("name", pr["author"]["login"]),
            "days_open": days_since(pr["createdAt"]),
            "is_draft": pr.get("isDraft", False),
            "ci_status": pr.get("ciStatus", "UNKNOWN"),
            "has_lgtm": "lgtm" in labels,
            "has_approved": "approved" in labels,
            "has_verified": any(l.startswith("verified") or l == "verified" for l in labels),
            "is_enhancements_repo": "enhancements" in pr.get("repository", ""),
        })

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8192,
        system=FILTER_SYSTEM_PROMPT.replace("{timestamp}", timestamp),
        messages=[
            {
                "role": "user",
                "content": f"Generate a filtered KMS team dashboard from these PRs:\n\n{json.dumps(pr_data, indent=2)}",
            }
        ],
    )

    # Extract markdown from response
    result_text = ""
    for block in response.content:
        if block.type == "text":
            result_text += block.text

    return result_text


async def main():
    """Main entry point."""
    import subprocess
    import sys

    print(f"Generating filtered dashboard for {KMS_TEAM['name']} team...")

    # Fetch all PRs
    result = get_team_prs(KMS_TEAM["authors"], KMS_TEAM["repos"])
    all_prs = result.get("prs", [])

    if not all_prs:
        print("No PRs found.")
        return

    print(f"Found {len(all_prs)} total PRs, generating dashboard with LLM...")

    # Generate markdown dashboard
    dashboard = await generate_dashboard(all_prs)

    # Create output directory
    output_dir = "briefings/team-dashboards"
    os.makedirs(output_dir, exist_ok=True)

    # Save dashboard
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_file = f"{output_dir}/kms-{timestamp}.md"

    with open(output_file, "w") as f:
        f.write(dashboard)

    print(f"\nDashboard saved to: {output_file}")
    print("\n" + "=" * 80)
    print(dashboard)

    # Post/update GitHub issue
    print("\n" + "=" * 80)
    print("Updating GitHub issue...")

    # Check if tracking issue exists by searching for title
    issue_number = None
    issue_title = "[Auto-Generated] KMS Team PR Dashboard"

    # Search for existing issue by title
    search_cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        "openshift/library-go",
        "--search",
        f'"{issue_title}" in:title',
        "--state",
        "open",
        "--json",
        "number",
        "--limit",
        "1",
    ]
    search_result = subprocess.run(search_cmd, capture_output=True, text=True)
    if search_result.returncode == 0 and search_result.stdout.strip():
        issues = json.loads(search_result.stdout)
        if issues:
            issue_number = str(issues[0]["number"])
            print(f"Found existing issue: #{issue_number}")

    if issue_number:
        # Update existing issue
        print(f"Updating issue #{issue_number} in openshift/library-go...")
        cmd = [
            "gh",
            "issue",
            "edit",
            issue_number,
            "--repo",
            "openshift/library-go",
            "--body",
            dashboard,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Updated: https://github.com/openshift/library-go/issues/{issue_number}")
        else:
            print(f"❌ Failed to update issue: {result.stderr}")
            sys.exit(1)
    else:
        # Create new issue
        print("Creating new tracking issue in openshift/library-go...")
        cmd = [
            "gh",
            "issue",
            "create",
            "--repo",
            "openshift/library-go",
            "--title",
            issue_title,
            "--body",
            dashboard,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            issue_url = result.stdout.strip()
            print(f"✅ Created: {issue_url}")
        else:
            print(f"❌ Failed to create issue: {result.stderr}")
            sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
