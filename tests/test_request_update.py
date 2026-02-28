"""
Test CLI for PM "Request Update" mode — multi-turn PM <-> Analyst dialogue.

Usage:
    python3 test_request_update.py                  # Run for NVDA (default)
    python3 test_request_update.py --company TSM    # Run for any ticker
    python3 test_request_update.py --show           # Print last session (no LLM)
    python3 test_request_update.py --show-all       # List all sessions (no LLM)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from models.update_session import UpdateSession


def show_session(filepath: Path):
    """Print a saved update session."""
    session = UpdateSession.load(str(filepath))
    sep = "─" * 60

    print(f"  Session ID:   {session.session_id}")
    print(f"  Ticker:       {session.ticker}")
    print(f"  Created:      {session.created_at[:19]}")
    print(f"  Completed:    {session.completed_at[:19] if session.completed_at else 'in progress'}")
    print(f"  LLM calls:    {session.llm_calls}")
    print(f"  Total tokens: {session.total_tokens:,}")

    if session.brief:
        print(f"\n  {sep}")
        print(f"  ANALYST BRIEF")
        print(f"  {sep}")
        print(f"  Summary:    {session.brief.summary}")
        print(f"  Confidence: {session.brief.confidence:.0%}")
        if session.brief.recommended_changes:
            print(f"  Recommended changes:")
            for drv, periods in session.brief.recommended_changes.items():
                for period, val in periods.items():
                    print(f"    {drv}[{period}] = {val:+.4f}")
        if session.brief.news_context:
            print(f"  News context ({len(session.brief.news_context)} headlines):")
            for h in session.brief.news_context[:5]:
                print(f"    - {h[:100]}")

    if session.challenges:
        print(f"\n  {sep}")
        print(f"  PM CHALLENGES ({len(session.challenges)})")
        print(f"  {sep}")
        for i, ch in enumerate(session.challenges, 1):
            print(f"  {i}. [{ch.challenge_type}] {ch.question}")
            print(f"     Targeting: {', '.join(ch.target_drivers)}")

    if session.responses:
        print(f"\n  {sep}")
        print(f"  ANALYST RESPONSES ({len(session.responses)})")
        print(f"  {sep}")
        for resp in session.responses:
            status = "CONCEDES" if resp.concedes else "DEFENDS"
            print(f"  [{status}] (challenge {resp.challenge_id})")
            print(f"    {resp.response}")
            print(f"    Confidence after: {resp.confidence_after:.0%}")
            if resp.revised_drivers:
                for drv, periods in resp.revised_drivers.items():
                    for period, val in periods.items():
                        print(f"    Revised: {drv}[{period}] = {val:+.4f}")

    if session.decision:
        print(f"\n  {sep}")
        print(f"  PM DECISION")
        print(f"  {sep}")
        print(f"  Action:     {session.decision.action.upper()}")
        print(f"  Confidence: {session.decision.confidence:.0%}")
        print(f"  Rationale:  {session.decision.rationale}")
        if session.decision.final_drivers:
            print(f"  Final drivers:")
            for drv, periods in session.decision.final_drivers.items():
                for period, val in periods.items():
                    print(f"    {drv}[{period}] = {val:+.4f}")
        if session.decision.valuation_result:
            vr = session.decision.valuation_result
            print(f"\n  VALUATION:")
            print(f"    Baseline price: ${vr.get('baseline_price', 0):,.2f}")
            print(f"    Updated price:  ${vr.get('updated_price', 0):,.2f}")
            print(f"    Upside:         {vr.get('upside', 0):+.1%}")


def show_all_sessions():
    """List all saved update sessions."""
    session_dir = config.UPDATE_SESSIONS_DIR
    files = sorted(session_dir.glob("*_update.json"), reverse=True)
    if not files:
        print("  No update sessions found.")
        return
    print(f"  {len(files)} update session(s) found:\n")
    for f in files:
        try:
            session = UpdateSession.load(str(f))
            action = session.decision.action.upper() if session.decision else "?"
            print(f"  {f.name}")
            print(f"    Ticker: {session.ticker} | Action: {action} | "
                  f"Challenges: {len(session.challenges)} | "
                  f"Tokens: {session.total_tokens:,}")
        except Exception as e:
            print(f"  {f.name} — error loading: {e}")


def run_update(ticker: str):
    """Run a full update dialogue."""
    from agents.pm_agent import PMAgent

    print("=" * 70)
    print(f"  TEST: PM Request Update — {ticker}")
    print("=" * 70)

    pm = PMAgent()
    session = pm.request_update(ticker)

    print("\n  Final result:")
    if session.decision:
        print(f"    Action: {session.decision.action.upper()}")
        if session.decision.valuation_result:
            vr = session.decision.valuation_result
            print(f"    Updated price: ${vr.get('updated_price', 0):,.2f}")
            print(f"    Upside: {vr.get('upside', 0):+.1%}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Test PM Request Update — multi-turn PM <-> Analyst dialogue"
    )
    parser.add_argument(
        '--company', type=str, default='NVDA',
        choices=list(config.COMPANIES.keys()),
        help='Target company ticker (default: NVDA)'
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--show', action='store_true',
                       help='Print last session for this ticker (no LLM)')
    group.add_argument('--show-all', action='store_true',
                       help='List all update sessions (no LLM)')
    args = parser.parse_args()

    if args.show_all:
        print("=" * 70)
        print("  ALL UPDATE SESSIONS")
        print("=" * 70)
        show_all_sessions()
        print("=" * 70)
        return

    if args.show:
        print("=" * 70)
        print(f"  LAST UPDATE SESSION — {args.company}")
        print("=" * 70)
        session_dir = config.UPDATE_SESSIONS_DIR
        files = sorted(session_dir.glob(f"*_{args.company}_update.json"), reverse=True)
        if not files:
            print(f"  No update sessions found for {args.company}.")
        else:
            show_session(files[0])
        print("=" * 70)
        return

    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    run_update(args.company)


if __name__ == '__main__':
    main()
