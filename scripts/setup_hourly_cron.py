#!/usr/bin/env python3
"""
Register an hourly cron job with your LangSmith Cloud deployment.

Run after deploying to LangSmith Cloud. Requires:
  - DEPLOYMENT_URL: your deployment's API URL (from LangSmith Deployments UI)
  - LANGCHAIN_API_KEY or LANGGRAPH_API_KEY: for auth (if required)

Usage:
  export DEPLOYMENT_URL="https://your-deployment-url.langsmith.cloud"
  python scripts/setup_hourly_cron.py

Cron runs at minute 0 of every hour (UTC). Input: autonomous news detection + NVDA.
To target another company or pass a specific event, edit the "input" dict below.
"""

import asyncio
import os


# Cron: every hour at :00 UTC
HOURLY_SCHEDULE = "0 * * * *"

# Graph/assistant ID as exposed by your langgraph.json (graphs.pipeline)
ASSISTANT_ID = "pipeline"

# Default input for each run (scheduled pipeline: detect latest news, value company)
DEFAULT_INPUT = {
    "event": "",  # empty = agents fetch latest semiconductor/macro news autonomously
    "company": "NVDA",
}


async def main():
    url = os.environ.get("DEPLOYMENT_URL")
    if not url:
        print("Error: set DEPLOYMENT_URL to your LangSmith deployment API URL")
        print("Example: export DEPLOYMENT_URL='https://xxx.langsmith.cloud'")
        return 1

    try:
        from langgraph_sdk import get_client
    except ImportError:
        print("Install the SDK: pip install langgraph-sdk")
        return 1

    client = get_client(url=url)

    # Stateless cron: creates a new thread each run, then deletes it (default)
    cron = await client.crons.create(
        ASSISTANT_ID,
        schedule=HOURLY_SCHEDULE,
        input=DEFAULT_INPUT,
        on_run_completed="delete",  # default; use "keep" to inspect runs later
    )
    print(f"Cron job created: {cron['cron_id']}")
    print(f"  Schedule: {HOURLY_SCHEDULE} (every hour at :00 UTC)")
    print(f"  Assistant: {ASSISTANT_ID}")
    print(f"  Input: {DEFAULT_INPUT}")
    print("\nTo remove later: client.crons.delete(cron_id)")
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
