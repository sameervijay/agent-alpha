"""
Lightweight test: NVDA Company News Analyst (ramp/monitor) → PM DCF application.
No debate, no other agents. Just: gather news → ramp or monitor → apply to DCF.

Usage:
    python3 test_analyst.py              # Auto-detect: ramp if no view, monitor if view exists
    python3 test_analyst.py --ramp       # Force ramp (re-establish baseline)
    python3 test_analyst.py --monitor    # Force monitor (requires existing view)
    python3 test_analyst.py --show       # Just print the current saved view, no LLM calls
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import config
from agents.company_analyst_agent import CompanyAnalystAgent
from pm_agent_interface import NVDADCFEngine


def show_view(analyst):
    """Print the saved view without any LLM calls."""
    view = analyst._load_view()
    if view is None:
        print(f"  No saved view for {analyst.ticker}. Run with --ramp first.")
        return
    print(f"  Ticker:      {view.ticker}")
    print(f"  Established: {view.established_at}")
    print(f"  Updated:     {view.last_updated}")
    print(f"  Confidence:  {view.confidence:.0%}")
    print(f"  Summary:     {view.summary}")
    print(f"  Headlines seen: {len(view.seen_headlines)}")
    print(f"  Drivers:")
    for driver, periods in view.baseline_drivers.items():
        for period, val in periods.items():
            print(f"    {driver}[{period}] = {val:+.4f}")
    if view.rationale:
        print(f"  Rationale:")
        for driver, reason in view.rationale.items():
            print(f"    {driver}: {reason[:120]}")


def run_test(mode):
    print("=" * 70)
    print("  TEST: NVDA Company News Analyst → DCF")
    print("=" * 70)

    analyst = CompanyAnalystAgent('NVDA')

    # Step 1: Gather news
    print("\n--- Step 1: Gather News ---")
    news_items = analyst.gather_news()
    print(f"  Gathered {len(news_items)} news items")
    for item in news_items[:5]:
        print(f"    [{item.source}] {item.date[:16] if item.date else 'N/A'} | {item.headline[:80]}")

    if not news_items:
        print("  No news found. Exiting.")
        return

    # Step 2: Ramp or Monitor
    print(f"\n--- Step 2: {mode.upper()} ---")
    if mode == 'ramp':
        view = analyst.ramp(news_items)
    elif mode == 'monitor':
        view = analyst.monitor(news_items)
    else:  # auto
        if analyst.has_view:
            print("  Existing view found → MONITOR mode")
            view = analyst.monitor(news_items)
        else:
            print("  No existing view → RAMP mode")
            view = analyst.ramp(news_items)

    print(f"\n  View summary: {view.summary}")
    print(f"  Confidence:   {view.confidence:.0%}")
    print(f"  Drivers:")
    for driver, periods in view.baseline_drivers.items():
        for period, val in periods.items():
            print(f"    {driver}[{period}] = {val:+.4f}")

    if not view.baseline_drivers:
        print("  No driver updates in view. Skipping DCF.")
        return

    # Step 3: Apply to DCF
    print("\n--- Step 3: Apply to DCF ---")
    nvda_config = config.COMPANIES['NVDA']
    engine = NVDADCFEngine(nvda_config['excel_path'])

    baseline = engine.compute_dcf()
    baseline_price = baseline['implied_price']
    print(f"  Baseline implied price: ${baseline_price:,.2f}")
    print(f"  Current market price:   ${baseline['current_price']:,.2f}")

    valid_drivers = set(engine.drivers.keys())
    delta_changes = {}
    for driver, periods in view.baseline_drivers.items():
        if driver not in valid_drivers:
            print(f"  Skipping unknown driver: {driver}")
            continue
        delta_changes[driver] = {}
        for period, delta in periods.items():
            current = engine.drivers.get(driver, {}).get(period, 0)
            delta_changes[driver][period] = current + delta

    engine.update_drivers(delta_changes)
    result = engine.compute_dcf()

    print(f"\n  Analyst-adjusted implied price: ${result['implied_price']:,.2f}")
    print(f"  Current market price:           ${result['current_price']:,.2f}")
    print(f"  Upside/Downside:                {result['upside']:+.1%}")
    alpha = result['implied_price'] - baseline_price
    print(f"  Alpha vs baseline:              ${alpha:+,.2f}")

    # Save
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = {
        'mode': mode,
        'ticker': 'NVDA',
        'timestamp': timestamp,
        'news_count': len(news_items),
        'analyst_summary': view.summary,
        'analyst_confidence': view.confidence,
        'driver_updates': view.baseline_drivers,
        'rationale': view.rationale,
        'baseline_price': baseline_price,
        'adjusted_price': result['implied_price'],
        'current_price': result['current_price'],
        'upside': result['upside'],
        'alpha': alpha,
    }
    filepath = config.VALUATIONS_DIR / f"{timestamp}_NVDA_analyst_test.json"
    with open(filepath, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n  Saved to {filepath}")

    print(f"\n  LLM calls: {len(analyst.call_log)}")
    print(f"  Total tokens: {analyst.total_tokens():,}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Test NVDA analyst ramp/monitor → DCF")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--ramp', action='store_true', help='Force ramp mode (re-establish baseline)')
    group.add_argument('--monitor', action='store_true', help='Force monitor mode')
    group.add_argument('--show', action='store_true', help='Print saved view, no LLM calls')
    args = parser.parse_args()

    if not config.OPENAI_API_KEY and not args.show:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    if args.show:
        analyst = CompanyAnalystAgent('NVDA')
        show_view(analyst)
        return

    if args.ramp:
        run_test('ramp')
    elif args.monitor:
        run_test('monitor')
    else:
        run_test('auto')


if __name__ == '__main__':
    main()
