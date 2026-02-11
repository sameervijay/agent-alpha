"""
News source abstraction layer — fetches from company IR RSS, SEC EDGAR, and finviz.
Module-level functions following the fred_data.py pattern.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

import config

# ── IR RSS Feed URLs ──────────────────────────────────────
_IR_RSS_FEEDS = {
    'NVDA': 'https://nvidianews.nvidia.com/rss',
    'ASML': 'https://www.asml.com/en/news/press-releases.rss',
}

# ── SEC EDGAR Mappings ────────────────────────────────────
_TICKER_TO_COMPANY = {
    'NVDA': 'NVIDIA',
    'TSM': 'Taiwan Semiconductor',
    'ASML': 'ASML',
    'CDNS': 'Cadence Design Systems',
    'CRWV': 'CoreWeave',
}

_EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"

# SEC requires a User-Agent header identifying the requester
_SEC_HEADERS = {
    'User-Agent': 'CS372-Agent research@stanford.edu',
    'Accept': 'application/json',
}

_last_sec_call = 0


def _sec_rate_limit():
    """SEC EDGAR requires at most 10 requests/second; we use 1s to be safe."""
    global _last_sec_call
    elapsed = time.time() - _last_sec_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_sec_call = time.time()


# ── Fetcher 1: Company IR RSS ─────────────────────────────

def fetch_ir_rss(ticker: str) -> list:
    """Parse company IR RSS feed. Returns list of dicts with headline/url/date/source fields.
    Returns empty list for tickers without known RSS feeds.
    """
    feed_url = _IR_RSS_FEEDS.get(ticker)
    if not feed_url:
        return []

    try:
        import feedparser
    except ImportError:
        print("  [news_fetcher] feedparser not installed, skipping IR RSS")
        return []

    try:
        feed = feedparser.parse(feed_url)
        items = []
        for entry in feed.entries[:20]:
            pub_date = ""
            if hasattr(entry, 'published'):
                pub_date = entry.published
            elif hasattr(entry, 'updated'):
                pub_date = entry.updated

            items.append({
                'headline': entry.get('title', ''),
                'url': entry.get('link', ''),
                'date': pub_date,
                'source': 'ir_rss',
                'ticker': ticker,
                'summary': entry.get('summary', '')[:300],
                'form_type': None,
            })
        return items
    except Exception as e:
        print(f"  [news_fetcher] IR RSS error for {ticker}: {e}")
        return []


# ── Fetcher 2: SEC EDGAR 8-K Filings ─────────────────────

def fetch_sec_edgar(ticker: str, days_back: int = 90) -> list:
    """Query SEC EDGAR full-text search for recent 8-K filings.
    Returns list of dicts with headline/url/date/source/form_type fields.
    """
    company_name = _TICKER_TO_COMPANY.get(ticker)
    if not company_name:
        return []

    _sec_rate_limit()
    try:
        date_from = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        date_to = datetime.now().strftime('%Y-%m-%d')
        params = {
            'q': f'"{company_name}"',
            'dateRange': 'custom',
            'startdt': date_from,
            'enddt': date_to,
            'forms': '8-K',
        }
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params=params,
            headers=_SEC_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        items = []
        for hit in data.get('hits', {}).get('hits', [])[:15]:
            source = hit.get('_source', {})
            display_names = source.get('display_names', [company_name])
            entity_name = display_names[0] if display_names else company_name
            form_type = source.get('form_type', '8-K')
            file_date = source.get('file_date', '')
            # Build a usable URL from the filing's accession number
            file_name = source.get('file_name', '')
            file_num = source.get('file_num', '')

            items.append({
                'headline': f"{entity_name} — {form_type} ({file_date})",
                'url': f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={company_name}&type=8-K&dateb=&owner=include&count=10",
                'date': file_date,
                'source': 'sec_edgar',
                'ticker': ticker,
                'summary': f"{form_type} filed by {entity_name} on {file_date}",
                'form_type': form_type,
            })
        return items
    except Exception as e:
        print(f"  [news_fetcher] SEC EDGAR error for {ticker}: {e}")
        return []


# ── Fetcher 3: finviz News Headlines ─────────────────────

def fetch_finviz(ticker: str) -> list:
    """Fetch news headlines from finviz. Universal fallback — works for every ticker.
    Returns list of dicts with headline/url/date/source fields.
    """
    try:
        from finvizfinance.quote import finvizfinance
    except ImportError:
        print("  [news_fetcher] finvizfinance not installed, skipping finviz")
        return []

    try:
        stock = finvizfinance(ticker)
        news_df = stock.ticker_news()

        items = []
        for _, row in news_df.head(20).iterrows():
            items.append({
                'headline': str(row.get('Title', '')),
                'url': str(row.get('Link', '')),
                'date': str(row.get('Date', '')),
                'source': 'finviz',
                'ticker': ticker,
                'summary': str(row.get('Title', '')),
                'form_type': None,
            })
        return items
    except Exception as e:
        print(f"  [news_fetcher] finviz error for {ticker}: {e}")
        return []


# ── Unified Entry Point ──────────────────────────────────

def fetch_all_news(ticker: str, use_cache: bool = True,
                   max_items: int = None) -> list:
    """Unified entry point: calls all 3 fetchers, deduplicates by URL, sorts by date.

    Cache: JSON files in data/news_cache/{ticker}_latest.json with 4-hour TTL.
    Every fetcher is wrapped in try/except — returns empty list on failure.
    """
    if max_items is None:
        max_items = config.NEWS_MAX_ITEMS

    # Check cache
    cache_path = config.NEWS_CACHE_DIR / f"{ticker}_latest.json"
    if use_cache and cache_path.exists():
        try:
            cache_data = json.loads(cache_path.read_text())
            cached_at = datetime.fromisoformat(cache_data.get('cached_at', ''))
            ttl = timedelta(hours=config.NEWS_CACHE_TTL_HOURS)
            if datetime.now() - cached_at < ttl:
                print(f"  [news_fetcher] Using cached news for {ticker}")
                return cache_data.get('items', [])[:max_items]
        except Exception:
            pass  # stale or corrupt cache, re-fetch

    # Fetch from all sources
    print(f"  [news_fetcher] Fetching news for {ticker}...")
    all_items = []

    for fetcher, name in [
        (fetch_ir_rss, 'IR RSS'),
        (fetch_sec_edgar, 'SEC EDGAR'),
        (fetch_finviz, 'finviz'),
    ]:
        try:
            items = fetcher(ticker)
            print(f"    {name}: {len(items)} items")
            all_items.extend(items)
        except Exception as e:
            print(f"    {name}: failed — {e}")

    # Deduplicate by URL
    seen_urls = set()
    unique_items = []
    for item in all_items:
        url = item.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)
        elif not url:
            unique_items.append(item)

    # Sort by date descending (best-effort parsing)
    def _parse_date(item):
        try:
            return datetime.fromisoformat(item.get('date', ''))
        except (ValueError, TypeError):
            return datetime.min

    unique_items.sort(key=_parse_date, reverse=True)
    unique_items = unique_items[:max_items]

    # Write cache
    try:
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'ticker': ticker,
            'items': unique_items,
        }
        cache_path.write_text(json.dumps(cache_data, indent=2))
    except Exception as e:
        print(f"  [news_fetcher] Cache write error: {e}")

    print(f"  [news_fetcher] Total for {ticker}: {len(unique_items)} unique items")
    return unique_items
