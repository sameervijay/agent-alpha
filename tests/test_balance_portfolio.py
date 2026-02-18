"""
Test CLI for PM Portfolio Balancing.

Analyzes all available DCF valuations and allocates portfolio across
S&P500 and individual stocks based on upside/downside and confidence.

Usage:
    python3 test_balance_portfolio.py         # Run portfolio allocation
    python3 test_balance_portfolio.py --show  # Show last allocation (no LLM)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from agents.pm_agent import PMAgent


def show_allocation(filepath: Path):
    """Display a saved portfolio allocation."""
    with open(filepath) as f:
        data = json.load(f)

    print("=" * 70)
    print("  SAVED PORTFOLIO ALLOCATION")
    print("=" * 70)
    print(f"  Timestamp:    {data.get('timestamp', 'unknown')}")
    print(f"  Risk Level:   {data.get('risk_level', 'unknown').upper()}")
    print(f"  Confidence:   {data.get('confidence', 0.0):.0%}")

    print("\n  ALLOCATIONS:")
    print("  " + "─" * 66)
    allocations = data.get('allocations', {})
    for ticker, weight in sorted(allocations.items(), key=lambda x: -x[1]):
        dollar_amt = weight * 1_000_000
        print(f"  {ticker:<6s}: {weight:>6.1%}  (${dollar_amt:>10,.0f})")
    print("  " + "─" * 66)

    if data.get('rationale'):
        print(f"\n  RATIONALE:")
        print(f"  {data['rationale']}")

    if data.get('valuations'):
        print("\n  UNDERLYING VALUATIONS:")
        print("  " + "─" * 66)
        for ticker, val in data['valuations'].items():
            print(f"  {ticker}: ${val['implied_price']:,.2f} vs ${val['current_price']:,.2f} "
                  f"= {val['upside']:+.1%} | Confidence: {val['confidence']:.0%}")

    if data.get('macro_context'):
        macro = data['macro_context']
        print(f"\n  MACRO CONTEXT:")
        print(f"  Outlook: {macro.get('outlook', 'unknown')}")
        print(f"  {macro.get('summary', 'N/A')[:200]}")

    print("=" * 70)


def run_balance():
    """Run portfolio balancing."""
    print("=" * 70)
    print("  TEST: PM Portfolio Balancing")
    print("=" * 70)

    pm = PMAgent()
    result = pm.balance_portfolio()

    # Summary
    print("\nPortfolio balancing complete.")
    print(f"  Total positions: {len(result['allocations'])}")
    print(f"  Largest position: {max(result['allocations'].items(), key=lambda x: x[1])[0]} "
          f"({max(result['allocations'].values()):.1%})")
    print(f"  SPY weight: {result['allocations'].get('SPY', 0):.1%}")
    print(f"  Overall confidence: {result['confidence']:.0%}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='Test PM Portfolio Balancing'
    )
    parser.add_argument('--show', action='store_true',
                       help='Show last allocation (no LLM)')
    args = parser.parse_args()

    if args.show:
        # Find most recent allocation file
        files = sorted(config.VALUATIONS_DIR.glob("*_portfolio_allocation.json"), reverse=True)
        if not files:
            print("No portfolio allocations found.")
            sys.exit(0)
        show_allocation(files[0])
        return

    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    run_balance()


if __name__ == '__main__':
    main()
