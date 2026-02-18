"""
Test: Cadence (CDNS) Company News Analyst in RAMP mode.

Gathers news for CDNS, establishes baseline view by interacting with macro analyst
for relevant macro factors, then applies the view to the CDNS DCF model.

Usage:
    python3 test_cdns_analyst.py              # Auto-detect: ramp if no view, monitor if view exists
    python3 test_cdns_analyst.py --ramp       # Force ramp (re-establish baseline)
    python3 test_cdns_analyst.py --monitor    # Force monitor (requires existing view)
    python3 test_cdns_analyst.py --show       # Just print the current saved view, no LLM calls
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import config
from agents.company_analyst_agent import CompanyAnalystAgent
from agents.macro_analyst_agent import MacroAnalystAgent
from cdns_engine import CDNSDCFEngine


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
    print("  TEST: CDNS Company News Analyst → DCF")
    print("=" * 70)

    analyst = CompanyAnalystAgent('CDNS')

    # Step 0: Check macro analyst for context
    print("\n--- Step 0: Macro Context ---")
    try:
        macro = MacroAnalystAgent()
        if macro.has_view:
            briefing = macro.get_latest_briefing()
            if briefing:
                print(f"  Macro outlook: {briefing.outlook}")
                cdns_note = briefing.company_notes.get('CDNS')
                if cdns_note:
                    print(f"  CDNS note: {cdns_note}")
            else:
                print("  No macro briefing available. Running macro analyst...")
                # Run macro ramp/monitor to establish view
                if not macro.has_view:
                    print("  Running macro RAMP...")
                    macro_view = macro.ramp()
                else:
                    print("  Running macro MONITOR...")
                    macro_view = macro.monitor()
                print(f"  Macro outlook: {macro_view.outlook}")
        else:
            print("  No macro view exists. Consider running test_macro_analyst.py first.")
    except Exception as e:
        print(f"  Could not load macro context: {e}")

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
    cdns_config = config.COMPANIES['CDNS']
    engine = CDNSDCFEngine(cdns_config['excel_path'])

    print("  Computing baseline DCF valuation...")
    baseline = engine.compute_dcf()
    baseline_price = baseline['implied_price']
    print(f"  Baseline implied price: ${baseline_price:,.2f}")
    print(f"  Current market price:   ${baseline['current_price']:,.2f}")
    print(f"  Baseline upside:        {baseline['upside']:+.1%}")

    # Apply analyst view
    print(f"\n  Applying analyst view drivers...")
    engine.update_drivers(view.baseline_drivers)
    updated = engine.compute_dcf()
    updated_price = updated['implied_price']

    print(f"\n  Updated implied price:  ${updated_price:,.2f}")
    print(f"  Price change:           ${updated_price - baseline_price:+,.2f} ({(updated_price/baseline_price - 1):+.1%})")
    print(f"  Updated upside:         {updated['upside']:+.1%}")

    # Summary table
    print("\n--- Valuation Summary ---")
    print(f"  {'Metric':<30s} {'Baseline':>15s} {'With View':>15s} {'Change':>15s}")
    print("  " + "-" * 77)
    print(f"  {'Implied Price':<30s} ${baseline_price:>13,.2f}  ${updated_price:>13,.2f}  "
          f"{updated_price - baseline_price:>+13,.2f}")
    print(f"  {'Upside to Current':<30s} {baseline['upside']:>14.1%}  {updated['upside']:>14.1%}  "
          f"{updated['upside'] - baseline['upside']:>+14.1%}")
    print(f"  {'Enterprise Value':<30s} ${baseline['enterprise_value']:>13,.0f}  "
          f"${updated['enterprise_value']:>13,.0f}  "
          f"${updated['enterprise_value'] - baseline['enterprise_value']:>+13,.0f}")

    print("\n=" * 70)
    print("  Test complete.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='Test CDNS Company News Analyst')
    parser.add_argument('--ramp', action='store_true', help='Force ramp mode (re-establish baseline)')
    parser.add_argument('--monitor', action='store_true', help='Force monitor mode')
    parser.add_argument('--show', action='store_true', help='Just show saved view, no LLM calls')
    args = parser.parse_args()

    if args.show:
        analyst = CompanyAnalystAgent('CDNS')
        show_view(analyst)
        return

    if args.ramp and args.monitor:
        print("Error: Cannot specify both --ramp and --monitor")
        sys.exit(1)

    mode = 'ramp' if args.ramp else ('monitor' if args.monitor else 'auto')
    run_test(mode)


if __name__ == '__main__':
    main()
