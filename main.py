#!/usr/bin/env python3
"""Developer workflow automation agent - main entry point for labeler and team dashboard."""

import argparse
import asyncio


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Developer workflow automation agent")
    parser.add_argument(
        "--mode",
        choices=["label-bot-prs", "team-dashboard", "personal-briefing"],
        required=True,
        help="Mode to run in",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't save state")

    args = parser.parse_args()

    if args.mode == "label-bot-prs":
        # Run the labeling agent
        from labeler import run_labeler
        run_labeler(dry_run=args.dry_run)
        return

    if args.mode == "team-dashboard":
        # Run the team dashboard generator (LLM-filtered markdown output)
        from team_dashboard import main as dashboard_main
        asyncio.run(dashboard_main())
        return

    if args.mode == "personal-briefing":
        # Run the personal briefing generator (posts to GitHub issue)
        from personal_briefing import main as briefing_main
        asyncio.run(briefing_main())
        return


if __name__ == "__main__":
    main()
