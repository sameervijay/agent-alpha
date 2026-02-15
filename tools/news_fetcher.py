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


# ── Fetcher 3: newsdata.io News API ─────────────────────

def fetch_newsdata_io(ticker: str, api_key: str = None) -> list:
    """Fetch news from newsdata.io with descriptions/summaries.
    Free tier: 200 credits/day, 10 articles per credit, 12-hour delay.
    Returns list of dicts with headline/url/date/source/description fields.
    """
    if not api_key:
        # Try to get from environment or config
        import os
        api_key = os.environ.get('NEWSDATA_IO_API_KEY')
        if not api_key:
            print("  [news_fetcher] newsdata.io API key not found, skipping")
            return []

    try:
        # Map ticker to search query
        ticker_queries = {
            'NVDA': 'NVIDIA OR NVDA',
            'CDNS': 'Cadence Design Systems OR CDNS',
            'TSM': 'Taiwan Semiconductor OR TSMC OR TSM',
            'ASML': 'ASML Holding OR ASML',
            'CWEV': 'CoreWeave OR CWEV',
        }
        query = ticker_queries.get(ticker, ticker)

        url = 'https://newsdata.io/api/1/news'
        params = {
            'apikey': api_key,
            'q': query,
            'language': 'en',
            'category': 'business,technology',
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('status') != 'success':
            print(f"  [news_fetcher] newsdata.io error: {data}")
            return []

        items = []
        for article in data.get('results', []):
            title = article.get('title', '')
            description = article.get('description', '')

            # Filter for relevance - title or description must mention the ticker or company
            ticker_variations = {
                'NVDA': ['nvidia', 'nvda'],
                'CDNS': ['cadence', 'cdns'],
                'TSM': ['taiwan semiconductor', 'tsmc', 'tsm'],
                'ASML': ['asml'],
                'CWEV': ['coreweave', 'cwev'],
            }

            search_terms = ticker_variations.get(ticker, [ticker.lower()])
            title_lower = title.lower()
            desc_lower = description.lower()

            # Check if article is actually about this ticker
            is_relevant = any(term in title_lower or term in desc_lower for term in search_terms)

            if not is_relevant:
                # Skip irrelevant articles
                continue

            # Get description (summary) - this is the key value on free tier
            if not description:
                description = title

            # Get content if available (paid plans only)
            content = article.get('content')
            if content and content != 'ONLY AVAILABLE IN PAID PLANS':
                # We have full content! Use it as summary
                description = content[:500]  # Truncate to 500 chars

            items.append({
                'headline': title,
                'url': article.get('link', ''),
                'date': article.get('pubDate', ''),
                'source': 'newsdata.io',
                'ticker': ticker,
                'summary': description,  # Real summary, not just headline!
                'form_type': None,
                'source_id': article.get('source_id', 'unknown'),
            })

        return items

    except Exception as e:
        print(f"  [news_fetcher] newsdata.io error for {ticker}: {e}")
        return []


# ── Fetcher 4: finviz News Headlines (Fallback) ──────────

def _extract_article_content(url: str, timeout: int = 10) -> str:
    """Extract full article text from URL using newspaper3k.
    Returns article text or empty string if extraction fails.
    """
    try:
        from newspaper import Article

        # Skip relative URLs or invalid URLs
        if not url or not url.startswith('http'):
            return ""

        article = Article(url)
        article.download()
        article.parse()

        # Return article text (typically 2000-5000 chars)
        return article.text
    except Exception:
        # Silently fail - not all URLs will work
        return ""


def fetch_finviz(ticker: str, extract_content: bool = True) -> list:
    """Fetch news headlines from finviz. Universal fallback — works for every ticker.

    Args:
        ticker: Stock ticker symbol
        extract_content: If True, attempts to extract full article text using newspaper3k

    Returns list of dicts with headline/url/date/source/summary fields.
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
            url = str(row.get('Link', ''))
            headline = str(row.get('Title', ''))

            # Try to extract full article content
            summary = headline  # Default to headline
            if extract_content and url.startswith('http'):
                article_text = _extract_article_content(url, timeout=5)
                if article_text and len(article_text) > 200:
                    # Use first 1000 chars of article as summary
                    summary = article_text[:1000]

            items.append({
                'headline': headline,
                'url': url,
                'date': str(row.get('Date', '')),
                'source': 'finviz',
                'ticker': ticker,
                'summary': summary,  # Now contains full article text if extraction succeeded!
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

    # Get newsdata.io API key from environment
    import os
    newsdata_api_key = os.environ.get('NEWSDATA_IO_API_KEY', 'pub_2cba889f251d4428abc4cdd004fcfc8a')

    for fetcher, name in [
        (fetch_ir_rss, 'IR RSS'),
        (lambda t: fetch_newsdata_io(t, newsdata_api_key), 'newsdata.io'),
        (fetch_finviz, 'finviz (fallback)'),
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
