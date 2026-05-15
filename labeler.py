#!/usr/bin/env python3
"""Automated PR labeling agent for bot-created PRs."""

import subprocess
import json
from typing import Dict, List, Any


BOT_AUTHORS = ["openshift-cherrypick-robot", "ocp-sustaining-admins", "openshift-bot"]
TARGET_REPOS = ["openshift/etcd", "openshift/cluster-etcd-operator"]


def get_pr_status(repo: str, pr_number: int) -> Dict[str, Any]:
    """Get PR status including labels and checks."""
    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "number,title,author,labels,reviewDecision,statusCheckRollup,state,url",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr}
    return json.loads(result.stdout)


def add_pr_comment(repo: str, pr_number: int, comment: str) -> Dict[str, Any]:
    """Add a comment to a PR via gh CLI."""
    cmd = [
        "gh",
        "pr",
        "comment",
        str(pr_number),
        "--repo",
        repo,
        "--body",
        comment,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr, "success": False}
    return {"success": True, "message": f"Comment added to {repo}#{pr_number}"}


def check_required_labels(pr_data: Dict[str, Any]) -> List[str]:
    """Check which Tide labels are missing from a PR."""
    labels = {label["name"] for label in pr_data.get("labels", [])}
    required_actions = []

    # Check for approval
    if "approved" not in labels:
        required_actions.append("/approve")

    # Check for backport-risk-assessed (common for cherrypicks)
    if "backport-risk-assessed" not in labels and pr_data.get("author", {}).get("login") == "openshift-cherrypick-robot":
        required_actions.append("/label backport-risk-assessed")

    # Check if all required tests passed
    status_rollup = pr_data.get("statusCheckRollup", [])
    if status_rollup:
        # Check if there are any required failing tests
        has_failing_required = any(
            check.get("state") in ["FAILURE", "ERROR"] and check.get("isRequired", False)
            for check in status_rollup
        )
        if not has_failing_required:
            # All required tests passed, check for verified label
            if "verified" not in labels:
                # For bot PRs that pass all tests, we can add verified
                required_actions.append("/verified by ci")

    return required_actions


def process_bot_pr(repo: str, pr_number: int, dry_run: bool = False) -> Dict[str, Any]:
    """Process a single bot PR and add required labels."""
    # Get PR status
    pr_data = get_pr_status(repo, pr_number)
    if "error" in pr_data:
        return {"error": f"Failed to get PR status: {pr_data['error']}"}

    # Check if PR is from a bot
    author = pr_data.get("author", {}).get("login", "")
    if author not in BOT_AUTHORS:
        return {"skipped": True, "reason": f"Not a bot PR (author: {author})"}

    # Check if PR is still open
    if pr_data.get("state") != "OPEN":
        return {"skipped": True, "reason": f"PR is {pr_data.get('state')}"}

    # Check which labels are needed
    required_actions = check_required_labels(pr_data)

    if not required_actions:
        return {"skipped": True, "reason": "No labels needed"}

    # Build comment
    comment_lines = [
        f"🤖 **Automated labeling by agent on behalf of @tjungblu**",
        "",
        "This is an automated bot PR. Adding required Tide labels:",
        "",
    ]
    for action in required_actions:
        comment_lines.append(action)

    comment_lines.extend([
        "",
        "---",
        "*This action was performed by an automated agent. If this is incorrect, please review and adjust manually.*"
    ])

    comment = "\n".join(comment_lines)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "pr": f"{repo}#{pr_number}",
            "author": author,
            "actions": required_actions,
            "comment": comment,
        }

    # Add comment with labels
    result = add_pr_comment(repo, pr_number, comment)

    if result.get("success"):
        return {
            "success": True,
            "pr": f"{repo}#{pr_number}",
            "author": author,
            "actions": required_actions,
            "url": pr_data.get("url"),
        }
    else:
        return {"error": result.get("error")}


def get_bot_prs_needing_labels() -> List[Dict[str, Any]]:
    """Get all bot PRs from target repos that might need labels."""
    prs = []

    for repo in TARGET_REPOS:
        for bot in BOT_AUTHORS:
            # Search for open PRs by this bot
            cmd = [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--author",
                bot,
                "--state",
                "open",
                "--json",
                "number,title,author,url",
                "--limit",
                "20",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                bot_prs = json.loads(result.stdout)
                for pr in bot_prs:
                    prs.append({
                        "repo": repo,
                        "number": pr["number"],
                        "title": pr["title"],
                        "author": pr["author"]["login"],
                        "url": pr["url"],
                    })

    return prs


def run_labeler(dry_run: bool = False):
    """Run the labeling agent on all bot PRs."""
    print("🤖 Starting automated PR labeling agent...")
    print(f"   Target repos: {', '.join(TARGET_REPOS)}")
    print(f"   Bot authors: {', '.join(BOT_AUTHORS)}")
    print(f"   Dry run: {dry_run}")
    print()

    # Get all bot PRs
    print("📋 Fetching bot PRs...")
    bot_prs = get_bot_prs_needing_labels()
    print(f"   Found {len(bot_prs)} bot PRs")
    print()

    if not bot_prs:
        print("✓ No bot PRs found to process")
        return

    # Process each PR
    results = {
        "processed": [],
        "skipped": [],
        "errors": [],
    }

    for pr in bot_prs:
        repo = pr["repo"]
        number = pr["number"]

        print(f"→ Processing {repo}#{number}: {pr['title'][:60]}...")
        result = process_bot_pr(repo, number, dry_run)

        if result.get("success"):
            results["processed"].append(result)
            actions = result.get("actions", [])
            print(f"  ✓ Added labels: {', '.join(actions)}")
            if dry_run:
                print(f"  📝 Would post comment:")
                for line in result.get("comment", "").split("\n"):
                    print(f"     {line}")
        elif result.get("skipped"):
            results["skipped"].append(result)
            print(f"  ⊘ Skipped: {result.get('reason')}")
        else:
            results["errors"].append(result)
            print(f"  ✗ Error: {result.get('error')}")
        print()

    # Summary
    print("=" * 60)
    print("Summary:")
    print(f"  Processed: {len(results['processed'])}")
    print(f"  Skipped: {len(results['skipped'])}")
    print(f"  Errors: {len(results['errors'])}")
    print()

    if results["processed"]:
        print("Processed PRs:")
        for r in results["processed"]:
            print(f"  • {r['pr']}: {', '.join(r['actions'])}")

    print()
    print("✓ Labeling agent complete!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Automated PR labeling agent")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually add comments")
    args = parser.parse_args()

    run_labeler(dry_run=args.dry_run)
