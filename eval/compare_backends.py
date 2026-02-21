"""
Backend Comparison: Original agents/ vs agents_langchain/

Runs both PM backends on the same event through --phase detect and prints
a side-by-side comparison of:
  - Events detected (count, headlines, severity, affected companies)
  - LLM calls made
  - Tokens consumed
  - Wall-clock time
  - Unique companies covered
  - Severity distribution

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


def run_backend(backend_name: str, event: str) -> dict:
    """Run event detection on one backend and collect metrics."""
    print(f"\n{'#' * 70}")
    print(f"  BACKEND: {backend_name.upper()}")
    print(f"{'#' * 70}")

    if backend_name == 'original':
        from agents.pm_agent import PMAgent
    else:
        from agents_langchain.pm_agent import PMAgent

    t0 = time.time()
    pm = PMAgent()
    init_time = time.time() - t0

    t1 = time.time()
    events = pm.detect_events(event)
    detect_time = time.time() - t1

    # Count LLM calls and tokens across PM + all domain agents
    llm_calls = 0
    total_tokens = 0

    # Original backend: agents have call_log / total_tokens()
    if backend_name == 'original':
        llm_calls += len(pm.call_log)
        total_tokens += pm.total_tokens()
        for agent in pm.domain_agents:
            if hasattr(agent, 'call_log'):
                llm_calls += len(agent.call_log)
                total_tokens += agent.total_tokens()

    return {
        'backend': backend_name,
        'events': events,
        'event_count': len(events),
        'init_time_s': round(init_time, 2),
        'detect_time_s': round(detect_time, 2),
        'total_time_s': round(init_time + detect_time, 2),
        'llm_calls': llm_calls,
        'total_tokens': total_tokens,
    }


def severity_dist(events: list) -> dict:
    dist = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    for e in events:
        dist[e.severity] = dist.get(e.severity, 0) + 1
    return dist


def unique_companies(events: list) -> set:
    companies = set()
    for e in events:
        companies.update(e.affected_companies)
    return companies


def print_comparison(orig: dict, lc: dict):
    col = 26

    def row(label, a, b):
        print(f"  {label:<{col}}  {str(a):<22}  {str(b)}")

    print("\n" + "=" * 75)
    print("  COMPARISON RESULTS")
    print("=" * 75)
    print(f"  {'Metric':<{col}}  {'Original':<22}  LangChain")
    print("  " + "-" * 70)

    row("Events detected",      orig['event_count'],    lc['event_count'])
    row("Init time (s)",        orig['init_time_s'],    lc['init_time_s'])
    row("Detection time (s)",   orig['detect_time_s'],  lc['detect_time_s'])
    row("Total time (s)",       orig['total_time_s'],   lc['total_time_s'])
    row("LLM calls",            orig['llm_calls'],      lc['llm_calls'])
    row("Tokens used",          orig['total_tokens'],   lc['total_tokens'])

    orig_cos = unique_companies(orig['events'])
    lc_cos = unique_companies(lc['events'])
    row("Companies covered",    len(orig_cos),          len(lc_cos))
    row("  tickers",            ', '.join(sorted(orig_cos)) or '—',
                                ', '.join(sorted(lc_cos)) or '—')

    orig_sev = severity_dist(orig['events'])
    lc_sev = severity_dist(lc['events'])
    for sev in ['critical', 'high', 'medium', 'low']:
        row(f"  severity={sev}", orig_sev[sev], lc_sev[sev])

    print("\n" + "=" * 75)
    print("  EVENTS SIDE BY SIDE")
    print("=" * 75)

    # Original events
    print(f"\n  [ORIGINAL]  {orig['event_count']} event(s)")
    orig_sorted = sorted(orig['events'], key=lambda e: SEV_ORDER.get(e.severity, 4))
    for i, e in enumerate(orig_sorted, 1):
        print(f"    {i}. [{e.severity.upper():8s}] [{e.direction:8s}] "
              f"{e.headline[:55]}")
        print(f"         Companies: {', '.join(e.affected_companies)}")

    # LangChain events
    print(f"\n  [LANGCHAIN]  {lc['event_count']} event(s)")
    lc_sorted = sorted(lc['events'], key=lambda e: SEV_ORDER.get(e.severity, 4))
    for i, e in enumerate(lc_sorted, 1):
        print(f"    {i}. [{e.severity.upper():8s}] [{e.direction:8s}] "
              f"{e.headline[:55]}")
        print(f"         Companies: {', '.join(e.affected_companies)}")

    # Assessment
    print("\n" + "=" * 75)
    print("  ASSESSMENT")
    print("=" * 75)

    speed_winner = "Original" if orig['detect_time_s'] < lc['detect_time_s'] else "LangChain"
    depth_winner = "LangChain" if lc['event_count'] >= orig['event_count'] else "Original"
    coverage_winner = "LangChain" if len(lc_cos) >= len(orig_cos) else "Original"

    print(f"  Speed:            {speed_winner} faster "
          f"({orig['detect_time_s']:.1f}s vs {lc['detect_time_s']:.1f}s)")
    print(f"  Event depth:      {depth_winner} detected more/equal events "
          f"({orig['event_count']} vs {lc['event_count']})")
    print(f"  Company coverage: {coverage_winner} covers more tickers "
          f"({len(orig_cos)} vs {len(lc_cos)})")

    if lc['total_tokens'] > 0 and orig['total_tokens'] > 0:
        print(f"  Token efficiency: "
              f"Original={orig['total_tokens']:,}  LangChain={lc['total_tokens']:,}")
    else:
        print(f"  Token efficiency: not tracked for LangChain agents (use LangSmith for tracing)")

    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Compare original vs LangChain backends")
    parser.add_argument('--event', type=str, default=DEFAULT_EVENT,
                        help='Event description to test with')
    parser.add_argument('--backend', type=str, default='both',
                        choices=['both', 'original', 'langchain'],
                        help='Which backend(s) to run (default: both)')
    args = parser.parse_args()

    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    print(f"\nEvent: {args.event}\n")

    if args.backend == 'both':
        orig_result = run_backend('original', args.event)
        lc_result = run_backend('langchain', args.event)
        print_comparison(orig_result, lc_result)
    elif args.backend == 'original':
        result = run_backend('original', args.event)
        print(f"\nOriginal: {result['event_count']} events in {result['detect_time_s']}s")
    else:
        result = run_backend('langchain', args.event)
        print(f"\nLangChain: {result['event_count']} events in {result['detect_time_s']}s")


if __name__ == '__main__':
    main()
