"""
Yahoo Finance data fetcher with rate limiting.
"""

import time

_last_call = 0
_RATE_LIMIT = 0.5  # seconds between calls


def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _RATE_LIMIT:
        time.sleep(_RATE_LIMIT - elapsed)
    _last_call = time.time()


def get_price(ticker: str) -> dict:
    """Get current price and basic info for a ticker."""
    _rate_limit()
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            'ticker': ticker,
            'price': info.get('currentPrice') or info.get('regularMarketPrice', 0),
            'market_cap': info.get('marketCap', 0),
            'pe_ratio': info.get('trailingPE', 0),
            'forward_pe': info.get('forwardPE', 0),
            'name': info.get('shortName', ticker),
        }
    except Exception as e:
        return {'ticker': ticker, 'error': str(e)}


def get_sector_performance(period: str = '1mo') -> dict:
    """Get semiconductor sector performance over a period."""
    _rate_limit()
    try:
        import yfinance as yf
        # Use SOXX (semiconductor ETF) as proxy
        soxx = yf.Ticker('SOXX')
        hist = soxx.history(period=period)
        if len(hist) >= 2:
            ret = (hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1
            return {'sector': 'Semiconductors (SOXX)', 'period': period, 'return': ret}
        return {'sector': 'Semiconductors (SOXX)', 'period': period, 'return': 0}
    except Exception as e:
        return {'error': str(e)}


def get_stock_history(ticker: str, period: str = '3mo') -> list:
    """Get price history for a ticker."""
    _rate_limit()
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        records = []
        for date, row in hist.iterrows():
            records.append({
                'date': date.strftime('%Y-%m-%d'),
                'close': float(row['Close']),
                'volume': int(row['Volume']),
            })
        return records
    except Exception as e:
        return [{'error': str(e)}]
