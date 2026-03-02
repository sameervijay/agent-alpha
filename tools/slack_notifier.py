"""
Slack notifier — posts live debate updates to the investment debate channel.
Silently no-ops if SLACK_BOT_TOKEN is not configured, so the pipeline never breaks.
"""

import requests
import config


_SLACK_MAX = 2900  # Slack silently truncates at 3000; leave margin for safety


def post(text: str) -> None:
    """Post a plain-text message to the configured Slack debate channel.
    Automatically splits messages that exceed Slack's 3000-char limit."""
    if not config.SLACK_BOT_TOKEN:
        return
    chunks = [text[i:i + _SLACK_MAX] for i in range(0, max(len(text), 1), _SLACK_MAX)]
    for chunk in chunks:
        try:
            requests.post(
                'https://slack.com/api/chat.postMessage',
                headers={'Authorization': f'Bearer {config.SLACK_BOT_TOKEN}'},
                json={'channel': config.SLACK_DEBATE_CHANNEL, 'text': chunk},
                timeout=5,
            )
        except Exception:
            pass
