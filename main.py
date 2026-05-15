#!/usr/bin/env python3
"""Developer workflow automation agent."""

import argparse
import asyncio
import json
import os
import sys
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from anthropic import AnthropicVertex
from dotenv import load_dotenv

from tools import GITHUB_TOOLS, execute_tool

# Load environment variables
load_dotenv()

# System prompt
SYSTEM_PROMPT = """You are a developer workflow automation assistant.

Your job is to:
1. Track GitHub PRs and Jira tickets assigned to the user
2. Identify blockers and urgent items
3. Sort items by recency (most recent first)
4. Take proactive actions like adding labels when appropriate
5. Generate concise briefs with actionable items

Guidelines:
- Always check previous state first to detect what's new or changed
- Focus on actionable items that need the user's attention
- Sort all items by recency (most recent PRs/changes first)
- **ALWAYS use markdown links** for PRs and Jira tickets (e.g., [openshift/repo#123](url), [JIRA-456](url))
- **Check PR author**: Only flag a PR as "yours" if the author.login matches the authenticated user (tjungblu)
- **NEVER show MERGED or CLOSED PRs** - filter them out completely from all sections
- Include bot PRs and automated backports (they're important to track)
- Keep briefs concise but informative

When generating the brief, structure it as:
1. **🆕 NEW**: Items that appeared since last check
2. **🚨 URGENT**: Items needing immediate attention
   - ONLY include items that are:
     * YOUR PRs with failing tests (MUST check: author.login == "tjungblu")
     * YOUR PRs with needs-rebase label (MUST check: author.login == "tjungblu")
     * Blocked PRs that you authored (MUST check: author.login == "tjungblu")
     * Critical Jira tickets (P0, blockers, In Progress with issues)
   - DO NOT include:
     * PRs authored by other people (dusk125, tiraboschi, etc.) even if they have failing tests
     * WIP/draft PRs authored by other people
3. **👀 REVIEW REQUESTS**: PRs where you are requested as reviewer, sorted by recency
   - **CRITICAL: Check PR state field - ONLY include PRs with state == "OPEN"**
   - **NEVER include PRs with state == "MERGED" or "CLOSED"**
   - Include all non-WIP OPEN PRs: human-authored, bot PRs, automated backports/cherrypicks
   - Exclude PRs with labels: do-not-merge/work-in-progress, do-not-merge/hold
   - Exclude PRs authored by you (those go in YOUR PRS section)
   - Use format: [repo#number](url) - title (author)
4. **✅ YOUR PRS**: Your open PRs (check author.login), sorted by recency
   - Show ALL your PRs (including WIP, draft, hold)
   - Flag important labels: needs-rebase, do-not-merge/work-in-progress, do-not-merge/hold
   - Flag failing tests
   - Use format: [repo#number](url) - title [labels if important]
5. **📝 TICKETS**: Active Jira tickets (In Progress, To Do, Planning)
   - Skip verified/closed tickets
   - Use markdown links: [TICKET-ID](url)
6. **🎯 ACTION ITEMS**: Top 3-5 concrete next steps
   - Prioritize: needs-rebase on your PRs > failing tests on your PRs > reviews > other

Format output as clean markdown with proper links.
"""


def save_brief_to_file(brief_content: str, is_morning: bool = False):
    """Save brief to markdown file in briefings/ folder."""
    import shutil as sh

    now = datetime.now()
    briefings_base = os.path.join(os.path.dirname(__file__), "briefings")

    if is_morning:
        # Morning briefs: briefings/YYYY/MM/DD-morning.md
        date_dir = os.path.join(briefings_base, now.strftime('%Y'), now.strftime('%m'))
        os.makedirs(date_dir, exist_ok=True)
        filename = f"{now.strftime('%d')}-morning.md"
    else:
        # Hourly briefs: briefings/YYYY/MM/DD/HHMM.md
        date_dir = os.path.join(briefings_base, now.strftime('%Y'), now.strftime('%m'), now.strftime('%d'))
        os.makedirs(date_dir, exist_ok=True)
        filename = f"{now.strftime('%H%M')}.md"

    filepath = os.path.join(date_dir, filename)

    # Write brief to file
    with open(filepath, "w") as f:
        f.write(brief_content)

    print(f"📄 Brief saved to: {filepath}")

    # For morning briefs, copy to ~/Desktop/morning-brief.md
    if is_morning:
        desktop_file = os.path.expanduser("~/Desktop/morning-brief.md")
        try:
            # Copy the file to desktop (replaces previous day's brief)
            sh.copy2(filepath, desktop_file)
            print(f"📋 Desktop copy updated: {desktop_file}")
        except Exception as e:
            print(f"Warning: Could not copy to desktop: {e}")


def init_client() -> AnthropicVertex:
    """Initialize Anthropic client via Vertex AI."""
    project_id = os.getenv("ANTHROPIC_VERTEX_PROJECT_ID")
    region = os.getenv("ANTHROPIC_VERTEX_REGION", "us-east5")

    if not project_id:
        print("Error: ANTHROPIC_VERTEX_PROJECT_ID not set")
        sys.exit(1)

    return AnthropicVertex(project_id=project_id, region=region)


async def get_mcp_tools(session):
    """Get tools from active MCP session."""
    if not session:
        return []

    try:
        tools_result = await session.list_tools()
        mcp_tools = []
        for tool in tools_result.tools:
            mcp_tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema if hasattr(tool, 'inputSchema') else {"type": "object", "properties": {}}
            })

        print(f"✓ Loaded {len(mcp_tools)} Jira/Atlassian tools from MCP server")
        return mcp_tools
    except Exception as e:
        print(f"Warning: Failed to list MCP tools: {e}")
        return []


async def execute_tool_async(tool_name: str, tool_input: Dict[str, Any], mcp_session: Optional[Any]) -> Dict[str, Any]:
    """Execute a tool (either GitHub via execute_tool or MCP via session)."""
    # Check if it's a GitHub tool
    if tool_name in ["get_my_prs", "get_prs_needing_review", "get_pr_details", "add_pr_label", "get_previous_state", "save_state"]:
        return execute_tool(tool_name, tool_input)

    # Otherwise it's an MCP tool
    if not mcp_session:
        return {"error": "MCP session not available"}

    try:
        result = await mcp_session.call_tool(tool_name, tool_input)
        # MCP returns content blocks, extract text
        if hasattr(result, 'content'):
            content_text = []
            for content in result.content:
                if hasattr(content, 'text'):
                    content_text.append(content.text)
            return {"result": "\n".join(content_text)}
        return {"result": str(result)}
    except Exception as e:
        return {"error": f"MCP tool execution failed: {str(e)}"}


async def run_brief_async(client: AnthropicVertex, mcp_session: Optional[Any], dry_run: bool = False, is_morning: bool = False):
    """Generate a workflow brief."""
    # Get MCP tools if session is available
    mcp_tools = await get_mcp_tools(mcp_session) if mcp_session else []

    # Combine GitHub and MCP tools
    all_tools = GITHUB_TOOLS + mcp_tools

    # Initial message
    messages = [
        {
            "role": "user",
            "content": f"""Generate my workflow brief for {datetime.now().strftime('%Y-%m-%d %H:%M')}.

Please:
1. Get the previous state to see what's changed
2. Get my current PRs
3. Get PRs where I'm requested as reviewer
4. Get my Jira tickets (if available)
5. Analyze what needs attention
6. Generate a concise brief with action items
7. Save the new state

Focus on what's urgent, blocked, or needs my immediate attention.

IMPORTANT: After all tools are executed, generate the final brief as clean markdown without any conversational text or tool descriptions.""",
        }
    ]

    print("Starting brief generation...\n")

    # Use streaming for real-time feedback
    with client.messages.stream(
        model="claude-sonnet-4-5",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=all_tools,
        messages=messages,
    ) as stream:
        # Tool use loop
        for event in stream:
            if event.type == "content_block_start":
                if event.content_block.type == "tool_use":
                    print(f"→ Using tool: {event.content_block.name}")
            elif event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)

        # Get the final message
        message = stream.get_final_message()

    # Continue with tool execution loop
    while message.stop_reason == "tool_use":
        # Extract tool calls and execute them
        tool_results = []
        for block in message.content:
            if block.type == "tool_use":
                print(f"→ Executing: {block.name}")

                # Execute the tool
                if dry_run and block.name == "save_state":
                    result = {"success": True, "message": "Dry run - state not saved"}
                else:
                    result = await execute_tool_async(block.name, block.input, mcp_session)

                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": str(result)}
                )

        # Append assistant message and tool results
        messages.append({"role": "assistant", "content": message.content})
        messages.append({"role": "user", "content": tool_results})

        # Continue the conversation
        with client.messages.stream(
            model="claude-sonnet-4-5",
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=all_tools,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        print(f"→ Using tool: {event.content_block.name}")
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        print(event.delta.text, end="", flush=True)

            message = stream.get_final_message()

    # Extract final brief text from last message (after all tools executed)
    brief_text = []
    for block in message.content:
        if hasattr(block, 'text'):
            brief_text.append(block.text)

    # Save brief to file
    brief_content = "".join(brief_text)
    if brief_content.strip():
        save_brief_to_file(brief_content, is_morning)

    print("\n\n✓ Brief generation complete!")


async def run_brief(client: AnthropicVertex, dry_run: bool = False, is_morning: bool = False):
    """Run brief with MCP session management."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # Find npx
    npx_path = shutil.which("npx")
    mcp_available = npx_path is not None

    if not mcp_available:
        print("Warning: npx not found, running without Jira integration")
        await run_brief_async(client, None, dry_run, is_morning)
        return

    try:
        # MCP server command
        server_params = StdioServerParameters(
            command=npx_path,
            args=["-y", "mcp-remote@latest", "https://mcp.atlassian.com/v1/mcp/authv2"],
        )

        # Keep MCP session alive for entire brief
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await run_brief_async(client, session, dry_run, is_morning)
    except Exception as e:
        print(f"Warning: MCP integration failed: {e}")
        print("Running brief without Jira integration")
        await run_brief_async(client, None, dry_run, is_morning)


def setup_mcp():
    """Set up MCP OAuth authentication."""
    print("Setting up Atlassian MCP authentication...")
    print("Run the following command to authenticate:")
    print()
    print("  npx -y mcp-remote@latest https://mcp.atlassian.com/v1/mcp/authv2")
    print()
    print("This will open a browser for OAuth. Once authenticated, credentials")
    print("are cached in ~/.mcp-auth for future use.")
    sys.exit(0)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Developer workflow automation agent")
    parser.add_argument(
        "--mode",
        choices=["brief", "check-pr", "setup-mcp"],
        default="brief",
        help="Mode to run in",
    )
    parser.add_argument("--pr", help="PR to check (format: owner/repo#123)")
    parser.add_argument("--dry-run", action="store_true", help="Don't save state")
    parser.add_argument("--morning", action="store_true", help="Mark as morning brief (creates desktop symlink)")

    args = parser.parse_args()

    if args.mode == "setup-mcp":
        setup_mcp()
        return

    # Initialize client
    client = init_client()

    if args.mode == "brief":
        asyncio.run(run_brief(client, dry_run=args.dry_run, is_morning=args.morning))
    elif args.mode == "check-pr":
        if not args.pr:
            print("Error: --pr required for check-pr mode")
            sys.exit(1)
        print(f"Check PR mode not yet implemented: {args.pr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
