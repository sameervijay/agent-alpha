"""
Test script to fetch live stock prices via the Stock Market Agent.

Usage:
    python3 test_stock_prices.py                      # Get market snapshot
    python3 test_stock_prices.py --ticker NVDA        # Get single ticker
    python3 test_stock_prices.py --tickers NVDA CDNS  # Get multiple tickers
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents.stock_market_agent import StockMarketAgent


def test_snapshot():
    """Get full market snapshot."""
    print("=" * 70)
    print("  MARKET SNAPSHOT")
    print("=" * 70)

    agent = StockMarketAgent()
    snapshot = agent.get_market_snapshot()

    print(f"\nTimestamp: {snapshot['timestamp']}")
    print(f"Summary: {snapshot['summary']}\n")

    print("Detailed prices:")
    print("-" * 70)
    for ticker in snapshot['tickers']:
        price_data = snapshot['prices'].get(ticker, {})
        if price_data.get('error'):
            print(f"  {ticker:<6s}: ERROR - {price_data['error']}")
        else:
            print(f"  {ticker:<6s}: ${price_data['price']:>8.2f}  "
                  f"({price_data['change_pct']:>+6.2%} from prev close)")

    print("=" * 70)


def test_single_ticker(ticker: str):
    """Get price for a single ticker."""
    print("=" * 70)
    print(f"  LIVE PRICE: {ticker}")
    print("=" * 70)

    agent = StockMarketAgent()
    price = agent.get_price(ticker, use_cache=False)

    if price > 0:
        print(f"\n  {ticker}: ${price:.2f}")
    else:
        print(f"\n  {ticker}: Could not fetch price")

    print("=" * 70)


def test_multiple_tickers(tickers: list):
    """Get prices for multiple tickers."""
    print("=" * 70)
    print(f"  LIVE PRICES: {', '.join(tickers)}")
    print("=" * 70)

    agent = StockMarketAgent()
    prices = agent.get_current_prices(tickers)

    print("\nResults:")
    print("-" * 70)
    for ticker, data in prices.items():
        if data.get('error'):
            print(f"  {ticker:<6s}: ERROR - {data['error']}")
        else:
            print(f"  {ticker:<6s}: ${data['price']:>8.2f}  "
                  f"({data['change_pct']:>+6.2%} from prev close)")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='Fetch live stock prices via Stock Market Agent'
    )
    parser.add_argument('--ticker', type=str,
                       help='Single ticker to fetch')
    parser.add_argument('--tickers', nargs='+',
                       help='Multiple tickers to fetch')
    args = parser.parse_args()

    if args.ticker:
        test_single_ticker(args.ticker)
    elif args.tickers:
        test_multiple_tickers(args.tickers)
    else:
        test_snapshot()


if __name__ == '__main__':
    main()
