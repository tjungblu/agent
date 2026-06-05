# Developer Workflow Automation Agent

Monitors GitHub PRs and Jira tickets, generates briefs with what needs attention.

## What It Does

- **Personal workflow briefing**: Tracks your GitHub PRs, review requests, and Jira tickets with hourly updates posted to a GitHub issue
- **Automated labeling agent**: Auto-labels bot PRs with required Tide labels (/approve, /verified, /label backport-risk-assessed)
- **Feature team PR dashboard**: Generates filtered dashboards for feature teams, posts to GitHub issues
- Identifies blockers, missing approvals, urgent items
- Generates briefs with prioritized action items
- Detects what changed since last run

## Architecture

### Components

**Scheduler** (systemd timers)
- Personal briefing: Every hour at :45 past the hour (creates GitHub issue)
- Bot PR labeler: Mon-Fri at 9:30 AM and 2:30 PM
- Team dashboard: Every hour at :15 past the hour

**Main Orchestrator** (main.py)
- Initializes Claude API client via Vertex AI
- Spawns MCP server process for Jira integration
- Manages the agentic loop (tool use → execution → feedback)
- Coordinates between tools and LLM
- Generates and outputs the brief

**Tools Layer** (tools.py)

GitHub Tools (via gh CLI):
- get_my_prs - Lists all PRs created by you
- get_prs_needing_review - PRs where you're requested as reviewer
- get_pr_details - Detailed PR info (reviews, checks, comments)
- add_pr_label - Add labels to PRs (urgent, needs-review, etc.)

Jira Tools (via Atlassian MCP Server):
- Dynamically provided by the MCP server
- Search issues, create/update tickets
- OAuth 2.1 authentication (no API tokens needed)

State Tools:
- get_previous_state - Load last run's state
- save_state - Persist current state for next run

**State Management** (state.json)
- Tracks last seen PR and ticket states
- Stores previous brief history
- Enables delta detection (what's new/changed)

**System Prompt**
- Guides Claude to check previous state first
- Focus on actionable items
- Prioritize: blocked > needs review > due soon
- Keep briefs concise
- Be proactive about suggesting actions

## How It Works

### Brief Generation Flow

1. Systemd timer triggers the script
2. Load previous run's state
3. Fetch current data (GitHub PRs via gh CLI, Jira tickets via MCP)
4. Claude analyzes data using tools
5. Identify changes from previous state
6. Prioritize items by urgency
7. Take proactive actions (add labels if needed)
8. Generate structured brief with action items
9. Save brief as markdown file
10. Save state for next run

### Automated Labeling Agent

The labeling agent automatically processes bot-created PRs and adds required Tide labels.

**Target PRs:**
- Repositories: openshift/etcd, openshift/cluster-etcd-operator
- Bot authors: openshift-cherrypick-robot, ocp-sustaining-admins, openshift-bot

**Actions:**
- Checks PR status and required Tide labels
- Adds /approve for all bot PRs
- Adds /label backport-risk-assessed for cherrypick PRs
- Adds /verified if all required tests pass
- Posts comment identifying the action was performed by the agent on behalf of you

**Schedule:** Runs twice daily (9:30 AM and 2:30 PM) to catch new bot PRs

### Personal Workflow Briefing

Unified hourly briefing that tracks your personal PRs, reviews, and Jira tickets, posted to a GitHub issue.

**Features:**
- Tracks your GitHub PRs across all repositories (downstream and upstream)
- Monitors review requests assigned to you
- Integrates Jira tickets via Atlassian MCP
- Detects changes since last run
- Generates action items prioritized by urgency
- Posts to GitHub issue that auto-updates on each run
- Saves historical briefs to local files

**Output:**
- Saved to: `briefings/YYYY/MM/DD/HHMM.md`
- Posted/updated in: GitHub issue in tjungblu/agent
- Issue title: "[Auto-Generated] Personal Workflow Brief"

### Feature Team PR Dashboard

Generates an LLM-filtered dashboard for feature teams, showing only relevant PRs with actionable items per person.

**Features:**
- Filters PRs by topic (e.g., KMS/Vault/encryption)
- Removes noise (fake bumps, test PRs, abandoned WIPs)
- Categorizes by action needed: /verified, /lgtm, CI fixes, etc.
- Prioritizes PRs (high/medium/low)
- Generates action items per team member
- Posts to GitHub issue that auto-updates on each run

**Configuration:**
Edit `team_dashboard.py` to customize:
- Team members (KMS_TEAM['authors'])
- Repositories (KMS_TEAM['repos'])
- Filtering criteria (FILTER_SYSTEM_PROMPT)

**Output:**
- Saved to: `briefings/team-dashboards/kms-{timestamp}.md`
- Posted/updated in: GitHub issue in openshift/library-go

### Brief Storage

All briefs and state are saved in the briefings/ folder:
- Personal briefs: briefings/YYYY/MM/DD/HHMM.md
- Team dashboards: briefings/team-dashboards/kms-{timestamp}.md
- State tracking: briefings/state.json

Example structure:
```
briefings/
├── state.json           ← Tracks changes between runs
├── team-dashboards/     ← Team PR dashboards
│   └── kms-20260605.md
└── 2026/
    └── 05/
        └── 15/
            ├── 0945.md  ← Personal briefings
            ├── 1045.md
            └── 1145.md
```

## Setup

### Prerequisites

1. **GitHub CLI** (gh) with authentication
2. **Google Cloud Authentication** (for Claude via Vertex AI)
3. **Atlassian MCP Server Access** (for Jira integration)
4. **Python 3.11+** with async support
5. **Node.js** (for npx to run MCP server)

### Installation

Run the automated installer:

1. Clone the repo and navigate to it
2. Copy .env.example to .env and configure it (set ANTHROPIC_VERTEX_PROJECT_ID and ATLASSIAN_SITE)
3. Run ./install.sh

The installer will:
- Check for required dependencies (uv, gh, npx)
- Install Python dependencies via uv
- Set up systemd user services for Jira MCP server and brief timers
- Enable and start all services

### Configuration

Edit .env with:
- ANTHROPIC_VERTEX_PROJECT_ID (your GCP project ID)
- ANTHROPIC_VERTEX_REGION (us-east5 or similar)
- ATLASSIAN_SITE (yourcompany.atlassian.net)
- Optional: BRIEF_SCHEDULE, OUTPUT_FORMAT

### Managing Services

**Check timer status:**
- systemctl --user status agent-personal-briefing.timer
- systemctl --user status agent-team-dashboard.timer

**View logs:**
- journalctl --user -u agent-personal-briefing.service -f
- journalctl --user -u agent-team-dashboard.service -f

**List upcoming brief times:**
- systemctl --user list-timers

**Trigger a brief manually:**
- systemctl --user start agent-personal-briefing.service

Note: MCP server spawns automatically when briefs run

## Usage

### Manual Run

All modes are run through `main.py`:

Generate personal briefing now (posts to GitHub issue):
- uv run python main.py --mode personal-briefing

Generate feature team PR dashboard:
- uv run python main.py --mode team-dashboard

Run bot PR labeler:
- uv run python main.py --mode label-bot-prs

Test labeler (dry run):
- uv run python main.py --mode label-bot-prs --dry-run

Browse all briefs:
- ls -lh briefings/

View GitHub issue (personal brief):
- Open https://github.com/tjungblu/agent/issues

### Example Output

The brief includes:
- New items since last check
- Urgent items needing immediate attention
- Review requests waiting for you
- Status of your open PRs
- Jira tickets in progress
- Top 3-5 action items

Output is structured with sections for new, urgent, review requests, your PRs, tickets, and action items.

