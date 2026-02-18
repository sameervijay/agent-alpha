"""
Test CLI for the Independent Macro Analyst Agent.

Usage:
    python3 test_macro_analyst.py              # Auto: ramp if no view, monitor if view exists
    python3 test_macro_analyst.py --ramp       # Force ramp (establish baseline)
    python3 test_macro_analyst.py --monitor    # Force monitor (check for changes)
    python3 test_macro_analyst.py --briefing   # Produce nightly briefing
    python3 test_macro_analyst.py --alerts     # Show pending alerts
    python3 test_macro_analyst.py --alerts --ticker NVDA
    python3 test_macro_analyst.py --show       # Print macro view (no LLM)
    python3 test_macro_analyst.py --show-briefing  # Print latest briefing (no LLM)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from agents.macro_analyst_agent import MacroAnalystAgent


def show_view(agent):
    """Print the saved macro view without any LLM calls."""
    view = agent.get_current_view()
    if view is None:
        print("  No saved macro view. Run with --ramp first.")
        return
    print(f"  Established: {view.established_at}")
    print(f"  Updated:     {view.last_updated}")
    print(f"  Outlook:     {view.outlook}")
    print(f"  Confidence:  {view.confidence:.0%}")
    print(f"  Summary:     {view.summary}")
    print(f"\n  Key Themes:")
    for theme in view.key_themes:
        print(f"    - {theme}")
    print(f"\n  Risk Factors:")
    for risk in view.risk_factors:
        print(f"    - {risk}")
    print(f"\n  Company Implications:")
    for ticker, note in view.company_implications.items():
        print(f"    {ticker}: {note}")
    print(f"\n  Indicator History:")
    for key, history in view.indicator_history.items():
        if history:
            latest = history[-1]
            print(f"    {key}: {latest['value']} (as of {latest['timestamp'][:19]})")


def show_briefing(agent):
    """Print the latest briefing without any LLM calls."""
    briefing = agent.get_latest_briefing()
    if briefing is None:
        print("  No briefings found. Run with --briefing first.")
        return
    print(f"  Date:    {briefing.date}")
    print(f"  Outlook: {briefing.outlook}")
    print(f"\n  Summary: {briefing.macro_summary}")
    print(f"\n  Indicator Table:")
    print(f"    {'Indicator':<25} {'Current':>10} {'Previous':>10} {'Change':>10}")
    print(f"    {'─' * 55}")
    for row in briefing.indicator_table:
        print(f"    {row['label']:<25} {row['current']:>10.2f} {row['previous']:>10.2f} "
              f"{row['change']:>+10.2f}")
    print(f"\n  Company Notes:")
    for ticker, note in briefing.company_notes.items():
        print(f"    {ticker}: {note}")
    print(f"\n  Key Themes:")
    for theme in briefing.key_themes:
        print(f"    - {theme}")
    print(f"\n  Risk Factors:")
    for risk in briefing.risk_factors:
        print(f"    - {risk}")


def show_alerts(agent, ticker=None):
    """Print pending (unacknowledged) alerts."""
    alerts = agent.get_pending_alerts(ticker)
    if not alerts:
        filter_text = f" for {ticker}" if ticker else ""
        print(f"  No pending alerts{filter_text}.")
        return
    print(f"  {len(alerts)} pending alert(s):\n")
    for alert in alerts:
        print(f"  [{alert.severity.upper()}] {alert.headline}")
        print(f"    ID:          {alert.id}")
        print(f"    Timestamp:   {alert.timestamp[:19]}")
        print(f"    Confidence:  {alert.confidence:.0%}")
        print(f"    Description: {alert.description}")
        print(f"    Indicators:  {', '.join(alert.affected_indicators)}")
        print(f"    Tickers:     {', '.join(alert.target_tickers)}")
        if alert.suggested_driver_impacts:
            print(f"    Suggested driver impacts:")
            for driver, periods in alert.suggested_driver_impacts.items():
                for period, val in periods.items():
                    print(f"      {driver}[{period}] = {val:+.4f}")
        print()


def run_ramp(agent):
    """Force ramp mode."""
    print("\n--- RAMP: Establishing baseline macro thesis ---")
    view = agent.ramp()
    print(f"\n  Outlook:    {view.outlook}")
    print(f"  Confidence: {view.confidence:.0%}")
    print(f"  Summary:    {view.summary}")
    print(f"\n  LLM calls: {len(agent.call_log)}")
    print(f"  Total tokens: {agent.total_tokens():,}")


def run_monitor(agent):
    """Force monitor mode."""
    print("\n--- MONITOR: Checking for macro changes ---")
    view, alerts = agent.monitor()
    print(f"\n  Outlook:    {view.outlook}")
    print(f"  Confidence: {view.confidence:.0%}")
    print(f"  Summary:    {view.summary}")
    if alerts:
        print(f"\n  {len(alerts)} alert(s) generated:")
        for alert in alerts:
            print(f"    [{alert.severity.upper()}] {alert.headline}")
    else:
        print(f"\n  No alerts generated.")
    print(f"\n  LLM calls: {len(agent.call_log)}")
    print(f"  Total tokens: {agent.total_tokens():,}")


def run_briefing(agent):
    """Produce nightly briefing."""
    print("\n--- NIGHTLY BRIEFING ---")
    briefing = agent.produce_nightly_briefing()
    print(f"\n  Outlook: {briefing.outlook}")
    print(f"  Summary: {briefing.macro_summary}")
    print(f"\n  LLM calls: {len(agent.call_log)}")
    print(f"  Total tokens: {agent.total_tokens():,}")


def run_auto(agent):
    """Auto-detect ramp vs monitor."""
    print("\n--- AUTO: Detecting mode ---")
    view, alerts = agent.run()
    print(f"\n  Outlook:    {view.outlook}")
    print(f"  Confidence: {view.confidence:.0%}")
    print(f"  Summary:    {view.summary}")
    if alerts:
        print(f"\n  {len(alerts)} alert(s) generated:")
        for alert in alerts:
            print(f"    [{alert.severity.upper()}] {alert.headline}")
    print(f"\n  LLM calls: {len(agent.call_log)}")
    print(f"  Total tokens: {agent.total_tokens():,}")


def main():
    parser = argparse.ArgumentParser(description="Test Independent Macro Analyst Agent")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--ramp', action='store_true', help='Force ramp mode (establish baseline)')
    group.add_argument('--monitor', action='store_true', help='Force monitor mode')
    group.add_argument('--briefing', action='store_true', help='Produce nightly briefing')
    group.add_argument('--alerts', action='store_true', help='Show pending alerts')
    group.add_argument('--show', action='store_true', help='Print macro view (no LLM)')
    group.add_argument('--show-briefing', action='store_true', help='Print latest briefing (no LLM)')
    parser.add_argument('--ticker', type=str, default=None,
                        help='Filter alerts by ticker (use with --alerts)')
    args = parser.parse_args()

    no_llm_modes = args.show or args.show_briefing or args.alerts
    if not config.OPENAI_API_KEY and not no_llm_modes:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    print("=" * 70)
    print("  TEST: Independent Macro Analyst Agent")
    print("=" * 70)

    agent = MacroAnalystAgent()

    if args.show:
        show_view(agent)
    elif args.show_briefing:
        show_briefing(agent)
    elif args.alerts:
        show_alerts(agent, args.ticker)
    elif args.ramp:
        run_ramp(agent)
    elif args.monitor:
        run_monitor(agent)
    elif args.briefing:
        run_briefing(agent)
    else:
        run_auto(agent)

    print("=" * 70)


if __name__ == '__main__':
    main()
