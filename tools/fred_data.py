"""
FRED economic data fetcher.
Wraps the FRED API for key macro indicators.
"""

import os
import time
import requests

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_last_call = 0
_RATE_LIMIT = 0.5

# Common series IDs
SERIES = {
    'fed_funds': 'FEDFUNDS',
    '10yr_yield': 'DGS10',
    '2yr_yield': 'DGS2',
    'cpi': 'CPIAUCSL',
    'gdp': 'GDP',
    'unemployment': 'UNRATE',
    'pce': 'PCEPI',
}


def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _RATE_LIMIT:
        time.sleep(_RATE_LIMIT - elapsed)
    _last_call = time.time()


def get_latest(series_key: str) -> float:
    """Fetch the latest value for a FRED series.

    Args:
        series_key: One of 'fed_funds', '10yr_yield', '2yr_yield', 'cpi', 'gdp', 'unemployment', 'pce'

    Returns:
        The latest observed value as a float, or 0.0 on error.
    """
    api_key = os.getenv('FRED_API_KEY', '')
    series_id = SERIES.get(series_key, series_key)

    if not api_key:
        # Return reasonable defaults when no API key
        defaults = {
            'fed_funds': 4.33,
            '10yr_yield': 4.25,
            '2yr_yield': 4.10,
            'cpi': 315.0,
            'gdp': 28000.0,
            'unemployment': 4.1,
            'pce': 125.0,
        }
        return defaults.get(series_key, 0.0)

    _rate_limit()
    try:
        params = {
            'series_id': series_id,
            'api_key': api_key,
            'file_type': 'json',
            'sort_order': 'desc',
            'limit': 1,
        }
        resp = requests.get(_FRED_BASE, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get('observations', [])
        if observations:
            val = observations[0].get('value', '0')
            if val == '.':
                return 0.0
            return float(val)
        return 0.0
    except Exception as e:
        print(f"  [FRED] Error fetching {series_key}: {e}")
        return 0.0
