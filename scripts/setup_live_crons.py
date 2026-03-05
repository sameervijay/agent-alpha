#!/usr/bin/env python3
"""
Manage live-trading cron jobs on LangGraph Platform.

Commands:
  python scripts/setup_live_crons.py list         # show all crons + their inputs
  python scripts/setup_live_crons.py recreate     # delete all, create 4 new live crons
  python scripts/setup_live_crons.py delete       # delete all crons
  python scripts/setup_live_crons.py run PROFILE  # fire one run manually right now

Requires LANGCHAIN_API_KEY (or LANGGRAPH_API_KEY) in env.
"""

import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DEPLOYMENT_URL = os.getenv(
    "DEPLOYMENT_URL",
    "https://agent-alpha-0a1713fb36b95d759bf691ed97acd509.us.langgraph.app",
)
ASSISTANT_ID = "024bfc19-7d06-5d5c-92b5-cec6be8620ae"

LIVE_CRONS = {
    "live_1h":  {"schedule": "0 * * * *",    "lookback_hours": 1},
    "live_4h":  {"schedule": "0 */4 * * *",  "lookback_hours": 4},
    "live_24h": {"schedule": "30 13 * * 1-5","lookback_hours": 24},
    "live_7d":  {"schedule": "30 13 * * 1",  "lookback_hours": 168},
}

COMPANY_TICKERS = ["NVDA", "CDNS", "CRWV", "TSM", "ASML"]


def _make_input(profile: str, lookback_hours: int) -> dict:
    return {
        "profile": profile,
        "lookback_hours": lookback_hours,
        "budget": 1000,
        "debate_rounds": 0,
    }


def cmd_list(client):
    crons = client.crons.search()
    if not crons:
        print("No cron jobs found.")
        return
    print(f"\n{'ID':<40} {'Schedule':<22} {'Profile':<12} Input")
    print("-" * 110)
    for c in crons:
        inp = c.get("input") or {}
        profile = inp.get("profile", "—")
        schedule = c.get("schedule", "?")
        cron_id = c.get("cron_id", "?")
        print(f"{cron_id:<40} {schedule:<22} {profile:<12} {inp}")
    print(f"\nTotal: {len(crons)} cron(s)")


def cmd_delete(client):
    crons = client.crons.search()
    if not crons:
        print("No crons to delete.")
        return
    for c in crons:
        cid = c["cron_id"]
        client.crons.delete(cid)
        profile = (c.get("input") or {}).get("profile", "?")
        print(f"  Deleted {cid}  (profile={profile})")
    print(f"Deleted {len(crons)} cron(s).")


def cmd_recreate(client):
    print("=== Deleting existing crons ===")
    cmd_delete(client)
    print("\n=== Creating 4 live crons ===")
    for profile, cfg in LIVE_CRONS.items():
        inp = _make_input(profile, cfg["lookback_hours"])
        cron = client.crons.create(
            ASSISTANT_ID,
            schedule=cfg["schedule"],
            input=inp,
        )
        print(f"  {profile:<10} schedule={cfg['schedule']:<18}  cron_id={cron['cron_id']}")
        print(f"             input={inp}")
    print(f"\nDone — {len(LIVE_CRONS)} crons registered.")


def cmd_run(client, profile: str):
    if profile not in LIVE_CRONS:
        print(f"Unknown profile '{profile}'. Choose from: {list(LIVE_CRONS)}")
        sys.exit(1)
    inp = _make_input(profile, LIVE_CRONS[profile]["lookback_hours"])
    thread = client.threads.create()
    run = client.runs.create(thread["thread_id"], ASSISTANT_ID, input=inp)
    print(f"  Triggered {profile}")
    print(f"  thread={thread['thread_id']}  run={run['run_id']}")
    print(f"  input={inp}")
    print("  Polling (every 15s)...")
    while True:
        r = client.runs.get(thread["thread_id"], run["run_id"])
        status = r.get("status", "?")
        print(f"  [{time.strftime('%H:%M:%S')}] status: {status}")
        if status in ("success", "error", "failed", "cancelled"):
            if status == "success":
                state = client.threads.get_state(thread["thread_id"])
                vals = state.get("values", {})
                alloc = (vals.get("result") or {}).get("allocation_dollars", {})
                print(f"  Allocation: {alloc}")
            break
        time.sleep(15)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    api_key = (os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGGRAPH_API_KEY")
               or os.getenv("LANGSMITH_API_KEY"))
    if not api_key:
        print("Error: set LANGCHAIN_API_KEY, LANGGRAPH_API_KEY, or LANGSMITH_API_KEY")
        sys.exit(1)

    from langgraph_sdk import get_sync_client
    client = get_sync_client(url=DEPLOYMENT_URL, api_key=api_key)

    if cmd == "list":
        cmd_list(client)
    elif cmd == "delete":
        cmd_delete(client)
    elif cmd == "recreate":
        cmd_recreate(client)
    elif cmd == "run":
        profile = sys.argv[2] if len(sys.argv) > 2 else "live_1h"
        cmd_run(client, profile)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
