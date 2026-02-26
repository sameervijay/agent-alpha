"""
Run event detection with the LangChain PM backend and print metrics.

Usage:
    python eval/compare_backends.py --event "Fed raises rates 25bps"
    python eval/compare_backends.py  # uses a default test event
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'config'))

import config

DEFAULT_EVENT = (
    "The US Bureau of Industry and Security announces tighter export controls "
    "on advanced AI chips to China, effective immediately."
)

SEV_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}


def run_detection(event: str) -> dict:
    """Run event detection with LangChain PM and return metrics."""
    from agents_langchain.pm_agent import PMAgent

    t0 = time.time()
    pm = PMAgent()
    init_time = time.time() - t0

    t1 = time.time()
    events = pm.detect_events(event)
    detect_time = time.time() - t1

    companies = set()
    for e in events:
        companies.update(e.affected_companies)

    sev_dist = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    for e in events:
        sev_dist[e.severity] = sev_dist.get(e.severity, 0) + 1

    print("\n" + "=" * 70)
    print("  LANGCHAIN BACKEND — EVENT DETECTION")
    print("=" * 70)
    print(f"  Init time:      {init_time:.2f}s")
    print(f"  Detection time: {detect_time:.2f}s")
    print(f"  Events:        {len(events)}")
    print(f"  Companies:     {', '.join(sorted(companies)) or '—'}")
    for sev in ['critical', 'high', 'medium', 'low']:
        print(f"    {sev}: {sev_dist[sev]}")
    print("\n  Events:")
    for i, e in enumerate(sorted(events, key=lambda x: SEV_ORDER.get(x.severity, 4)), 1):
        print(f"    {i}. [{e.severity}] [{e.direction}] {e.headline[:55]}")
    print("=" * 70 + "\n")

    return {
        'events': events,
        'event_count': len(events),
        'init_time_s': round(init_time, 2),
        'detect_time_s': round(detect_time, 2),
        'companies': companies,
    }


def main():
    parser = argparse.ArgumentParser(description="Run LangChain backend event detection")
    parser.add_argument('--event', type=str, default=DEFAULT_EVENT,
                        help='Event description to test with')
    args = parser.parse_args()

    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    print(f"\nEvent: {args.event}\n")
    run_detection(args.event)


if __name__ == '__main__':
    main()
