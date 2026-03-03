"""
Slack Bot — PM Portfolio Status on @mention.

Listens for @mentions via Socket Mode and responds with portfolio status.

Usage:
    python tools/slack_listener.py

Requires env vars:
    SLACK_BOT_TOKEN  — xoxb-... Bot User OAuth Token
    SLACK_APP_TOKEN  — xapp-... App-Level Token for Socket Mode

Slack App setup:
    1. Enable Socket Mode in your Slack app settings (generates xapp- token)
    2. Subscribe to bot events: app_mention
    3. Add bot scopes: app_mentions:read, chat:write
    4. Install/reinstall app to workspace
"""

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
except ImportError:
    print("Error: slack-bolt not installed. Run: pip install 'slack-bolt>=1.18'")
    sys.exit(1)


app = App(token=config.SLACK_BOT_TOKEN)


_HELP_TEXT = (
    "*PM Bot Commands*\n"
    "Mention me with one of these:\n"
    "  `@PM status` — Full debate PM portfolio\n"
    "  `@PM status nodebate` — No-debate PM portfolio\n"
    "  `@PM status noanalysts` — No-analysts PM portfolio\n"
    "  `@PM status all` — All portfolio profiles\n"
    "  `@PM help` — Show this help message\n"
    "\n_Any mention without a keyword defaults to full-debate portfolio status._"
)


def _parse_command(text: str) -> tuple[str, str]:
    """Extract the command keyword and profile from a mention text.

    Returns (command, profile). Profile defaults to "pm".
    """
    import re
    cleaned = re.sub(r"<@\w+>", "", text).strip().lower()

    if "help" in cleaned:
        return "help", "pm"

    # Check for profile keywords
    if "noanalyst" in cleaned:
        return "status", "pm_noanalysts"
    if "nodebate" in cleaned:
        return "status", "pm_nodebate"
    if "all" in cleaned:
        return "status_all", "pm"

    return "status", "pm"


@app.event("app_mention")
def handle_mention(event: dict, say):
    """Respond to @PM mentions with portfolio status or help."""
    text = event.get("text", "")
    thread_ts = event.get("ts")  # reply in thread

    command, profile = _parse_command(text)

    if command == "help":
        say(text=_HELP_TEXT, thread_ts=thread_ts)
        return

    try:
        from eval.pm_portfolio import get_portfolio_status, format_status_for_slack, PROFILES

        if command == "status_all":
            # Show all profiles
            blocks = []
            for p in PROFILES:
                status = get_portfolio_status(profile=p)
                blocks.append(format_status_for_slack(status, profile=p))
            say(text="\n\n".join(blocks), thread_ts=thread_ts)
        else:
            # Single profile
            status = get_portfolio_status(profile=profile)
            slack_text = format_status_for_slack(status, profile=profile)
            say(text=slack_text, thread_ts=thread_ts)
    except Exception as e:
        say(text=f"Error retrieving portfolio status: {e}", thread_ts=thread_ts)


def main():
    if not config.SLACK_BOT_TOKEN:
        print("Error: SLACK_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not config.SLACK_APP_TOKEN:
        print("Error: SLACK_APP_TOKEN not set in .env (needed for Socket Mode)")
        print("Generate one at https://api.slack.com/apps → Basic Information → App-Level Tokens")
        print("  Scope needed: connections:write")
        sys.exit(1)

    print("Starting PM Slack bot in Socket Mode...")
    print(f"  Bot token: {config.SLACK_BOT_TOKEN[:10]}...")
    print(f"  App token: {config.SLACK_APP_TOKEN[:10]}...")
    print("  Listening for @mentions. Press Ctrl+C to stop.\n")

    handler = SocketModeHandler(app, config.SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    main()
