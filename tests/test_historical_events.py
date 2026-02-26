"""
Test script for historical event detection and causality analysis.

Usage:
    python3 test_historical_events.py                    # Analyze NVDA (default)
    python3 test_historical_events.py --ticker CDNS      # Analyze specific ticker
    python3 test_historical_events.py --sigma 2.5        # Higher threshold
    python3 test_historical_events.py --days 500         # Longer lookback
    python3 test_historical_events.py --max-events 10    # More events
    python3 test_historical_events.py --all              # Analyze all 5 companies
    python3 test_historical_events.py --save             # Save results to JSON
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import config
from agents_langchain.stock_market_agent import StockMarketAgent


def analyze_ticker(agent: StockMarketAgent, ticker: str, sigma: float = 2.0,
                   lookback_days: int = 252, max_events: int = 5) -> dict:
    """Run full historical event analysis for a ticker."""

    # Get company info
    company_info = config.COMPANIES.get(ticker, {})
    company_name = company_info.get('name', ticker)

    print(f"\n{'=' * 70}")
    print(f"  ANALYZING: {company_name} ({ticker})")
    print(f"  Sigma threshold: {sigma}")
    print(f"  Lookback: {lookback_days} trading days")
    print(f"  Max events: {max_events}")
    print(f"{'=' * 70}")

    # Run analysis
    events = agent.analyze_historical_events(
        ticker=ticker,
        sigma=sigma,
        lookback_days=lookback_days,
        max_events=max_events
    )

    # Compile results
    result = {
        'ticker': ticker,
        'company_name': company_name,
        'analysis_date': datetime.now().isoformat(),
        'parameters': {
            'sigma': sigma,
            'lookback_days': lookback_days,
            'max_events': max_events,
        },
        'events': events,
        'summary': {
            'total_events': len(events),
            'fundamental_driven': sum(1 for e in events if e['causality'].get('has_fundamental_reason', False)),
            'technical_driven': sum(1 for e in events if not e['causality'].get('has_fundamental_reason', False)),
        },
    }

    return result


def print_detailed_summary(result: dict):
    """Print a detailed summary of analysis results."""

    ticker = result['ticker']
    summary = result['summary']
    events = result['events']

    print(f"\n{'=' * 70}")
    print(f"  DETAILED SUMMARY: {ticker}")
    print(f"{'=' * 70}")
    print(f"  Total events: {summary['total_events']}")
    print(f"  Fundamental-driven: {summary['fundamental_driven']}")
    print(f"  Technical/sentiment: {summary['technical_driven']}")
    print()

    # Event type breakdown
    event_types = {}
    for event in events:
        event_type = event['causality'].get('event_type', 'unknown')
        event_types[event_type] = event_types.get(event_type, 0) + 1

    print("  Event type breakdown:")
    for event_type, count in sorted(event_types.items(), key=lambda x: x[1], reverse=True):
        print(f"    {event_type}: {count}")

    # High-confidence fundamental events
    print(f"\n  High-confidence fundamental events:")
    fundamental_events = [
        e for e in events
        if e['causality'].get('has_fundamental_reason', False) and
           e['causality'].get('confidence', 0) >= 0.7
    ]

    if fundamental_events:
        for i, event in enumerate(fundamental_events, 1):
            print(f"\n    {i}. {event['date']} - {event['return_pct']:+.2%} move")
            print(f"       Type: {event['causality']['event_type']}")
            print(f"       Catalyst: {event['causality']['primary_catalyst'][:100]}")
            print(f"       Confidence: {event['causality']['confidence']:.0%}")
    else:
        print("    None found (all events below 70% confidence threshold)")

    print(f"\n{'=' * 70}")


def save_results(results: list, output_dir: Path):
    """Save analysis results to JSON files."""

    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    for result in results:
        ticker = result['ticker']
        filename = f"{timestamp}_{ticker}_historical_events.json"
        filepath = output_dir / filename

        # Convert news_items to serializable format (remove DataFrame if any)
        serializable_result = result.copy()
        for event in serializable_result['events']:
            # Remove non-serializable objects
            if 'news_items' in event:
                for item in event['news_items']:
                    # Keep only basic fields
                    for key in list(item.keys()):
                        if key not in ['headline', 'url', 'date', 'source', 'summary', 'ticker']:
                            item.pop(key, None)

        with open(filepath, 'w') as f:
            json.dump(serializable_result, f, indent=2)

        print(f"  ✅ Saved {ticker} results to: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze historical volatility events and news causality"
    )
    parser.add_argument(
        '--ticker', type=str, default='NVDA',
        choices=list(config.COMPANIES.keys()),
        help='Stock ticker to analyze (default: NVDA)'
    )
    parser.add_argument(
        '--sigma', type=float, default=2.0,
        help='Sigma threshold for event detection (default: 2.0)'
    )
    parser.add_argument(
        '--days', type=int, default=252,
        help='Lookback period in trading days (default: 252 = 1 year)'
    )
    parser.add_argument(
        '--max-events', type=int, default=5,
        help='Maximum number of events to analyze (default: 5)'
    )
    parser.add_argument(
        '--all', action='store_true',
        help='Analyze all 5 semiconductor companies'
    )
    parser.add_argument(
        '--save', action='store_true',
        help='Save results to JSON files in data/historical_events/'
    )

    args = parser.parse_args()

    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    # Initialize agent
    print("Initializing Stock Market Agent...")
    agent = StockMarketAgent()

    # Determine tickers to analyze
    tickers = list(config.COMPANIES.keys()) if args.all else [args.ticker]

    # Run analysis for each ticker
    results = []
    for ticker in tickers:
        result = analyze_ticker(
            agent=agent,
            ticker=ticker,
            sigma=args.sigma,
            lookback_days=args.days,
            max_events=args.max_events
        )
        results.append(result)

        # Print detailed summary
        print_detailed_summary(result)

    # Save results if requested
    if args.save:
        output_dir = config.DATA_DIR / 'historical_events'
        print(f"\nSaving results to {output_dir}/...")
        save_results(results, output_dir)
        print("✅ All results saved.")

    # Cross-ticker summary if analyzing multiple
    if len(results) > 1:
        print(f"\n{'=' * 70}")
        print("  CROSS-TICKER SUMMARY")
        print(f"{'=' * 70}")

        for result in results:
            ticker = result['ticker']
            summary = result['summary']
            fundamental_pct = (summary['fundamental_driven'] / summary['total_events'] * 100
                             if summary['total_events'] > 0 else 0)
            print(f"  {ticker:6s}: {summary['total_events']} events, "
                  f"{summary['fundamental_driven']} fundamental ({fundamental_pct:.0f}%)")

        print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
