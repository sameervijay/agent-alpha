"""
Macro news source abstraction layer — fetches from Alpha Vantage, CNBC RSS,
Finnhub, and government RSS feeds (Fed/BLS/BEA).
Module-level functions following the news_fetcher.py pattern.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

import config
import sys
from pathlib import Path

# Import macro_analyst_config from config folder
sys.path.insert(0, str(Path(__file__).parent.parent / 'config'))
import macro_analyst_config as mcfg


# ── Helper: Alpha Vantage timestamp parsing ──────────────

def _parse_av_timestamp(ts: str) -> str:
    """Convert Alpha Vantage YYYYMMDDTHHMMSS format to ISO 8601."""
    try:
        m = re.match(r'(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})', ts)
        if m:
            return f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}"
    except Exception:
        pass
    return ts


# ── Fetcher 1: Alpha Vantage NEWS_SENTIMENT ──────────────

def fetch_alpha_vantage_news() -> list:
    """Fetch macro news from Alpha Vantage NEWS_SENTIMENT API.
    Returns list of dicts with headline/url/date/source/summary/sentiment/sentiment_score.
    Requires ALPHA_VANTAGE_API_KEY in .env.
    """
    api_key = os.getenv('ALPHA_VANTAGE_API_KEY', '')
    if not api_key:
        print("  [macro_news] Alpha Vantage API key not set, skipping")
        return []

    try:
        resp = requests.get(
            'https://www.alphavantage.co/query',
            params={
                'function': 'NEWS_SENTIMENT',
                'topics': mcfg.ALPHA_VANTAGE_TOPICS,
                'apikey': api_key,
                'limit': 50,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items = []
        for article in data.get('feed', []):
            items.append({
                'headline': article.get('title', ''),
                'url': article.get('url', ''),
                'date': _parse_av_timestamp(article.get('time_published', '')),
                'source': 'alpha_vantage',
                'summary': article.get('summary', '')[:300],
                'sentiment': article.get('overall_sentiment_label', ''),
                'sentiment_score': float(article.get('overall_sentiment_score', 0)),
            })
        return items
    except Exception as e:
        print(f"  [macro_news] Alpha Vantage error: {e}")
        return []


# ── Fetcher 2: CNBC Economy RSS ──────────────────────────

def fetch_cnbc_macro_rss() -> list:
    """Parse CNBC Economy RSS feed. Returns list of dicts.
    No API key required (free RSS).
    """
    try:
        import feedparser
    except ImportError:
        print("  [macro_news] feedparser not installed, skipping CNBC RSS")
        return []

    try:
        feed = feedparser.parse(mcfg.CNBC_ECONOMY_RSS_URL)
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
                'source': 'cnbc_rss',
                'summary': entry.get('summary', '')[:300],
            })
        return items
    except Exception as e:
        print(f"  [macro_news] CNBC RSS error: {e}")
        return []


# ── Fetcher 3: Finnhub Market News ───────────────────────

def fetch_finnhub_news() -> list:
    """Fetch general market news from Finnhub API (raw requests, not finnhub-python).
    Returns list of dicts. Requires FINNHUB_API_KEY in .env.
    """
    api_key = os.getenv('FINNHUB_API_KEY', '')
    if not api_key:
        print("  [macro_news] Finnhub API key not set, skipping")
        return []

    try:
        resp = requests.get(
            'https://finnhub.io/api/v1/news',
            params={
                'category': mcfg.FINNHUB_NEWS_CATEGORY,
                'token': api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items = []
        for article in data[:30]:
            # Finnhub uses Unix timestamps
            ts = article.get('datetime', 0)
            date_str = datetime.fromtimestamp(ts).isoformat() if ts else ''

            items.append({
                'headline': article.get('headline', ''),
                'url': article.get('url', ''),
                'date': date_str,
                'source': 'finnhub',
                'summary': article.get('summary', '')[:300],
            })
        return items
    except Exception as e:
        print(f"  [macro_news] Finnhub error: {e}")
        return []


# ── Fetcher 4: Government RSS Feeds (Fed/BLS/BEA) ───────

def fetch_macro_rss_feeds() -> list:
    """Parse government RSS feeds defined in mcfg.MACRO_NEWS_SOURCES.
    Returns list of dicts with source tag based on feed URL.
    """
    try:
        import feedparser
    except ImportError:
        print("  [macro_news] feedparser not installed, skipping government RSS")
        return []

    # Map feed URLs to source tags
    source_map = {
        'federalreserve.gov': 'fed_rss',
        'bls.gov': 'bls_rss',
        'bea.gov': 'bea_rss',
    }

    items = []
    for feed_url in mcfg.MACRO_NEWS_SOURCES:
        # Determine source tag from URL
        source_tag = 'gov_rss'
        for domain, tag in source_map.items():
            if domain in feed_url:
                source_tag = tag
                break

        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                pub_date = ""
                if hasattr(entry, 'published'):
                    pub_date = entry.published
                elif hasattr(entry, 'updated'):
                    pub_date = entry.updated

                items.append({
                    'headline': entry.get('title', ''),
                    'url': entry.get('link', ''),
                    'date': pub_date,
                    'source': source_tag,
                    'summary': entry.get('summary', '')[:300],
                })
        except Exception as e:
            print(f"  [macro_news] RSS error for {feed_url}: {e}")
            continue

    return items


# ── Unified Entry Point ──────────────────────────────────

def fetch_all_macro_news(use_cache: bool = True, max_items: int = None) -> list:
    """Unified entry point: calls all 4 fetchers, deduplicates by URL, sorts by date.

    Cache: JSON file at data/news_cache/macro_latest.json with 4-hour TTL.
    Every fetcher is wrapped in try/except — returns empty list on failure.
    """
    if max_items is None:
        max_items = mcfg.MACRO_NEWS_MAX_ITEMS

    # Check cache
    cache_path = config.NEWS_CACHE_DIR / 'macro_latest.json'
    if use_cache and cache_path.exists():
        try:
            cache_data = json.loads(cache_path.read_text())
            cached_at = datetime.fromisoformat(cache_data.get('cached_at', ''))
            ttl = timedelta(hours=config.NEWS_CACHE_TTL_HOURS)
            if datetime.now() - cached_at < ttl:
                print("  [macro_news] Using cached macro news")
                return cache_data.get('items', [])[:max_items]
        except Exception:
            pass  # stale or corrupt cache, re-fetch

    # Fetch from all sources
    print("  [macro_news] Fetching macro news from all sources...")
    all_items = []

    for fetcher, name in [
        (fetch_alpha_vantage_news, 'Alpha Vantage'),
        (fetch_cnbc_macro_rss, 'CNBC RSS'),
        (fetch_finnhub_news, 'Finnhub'),
        (fetch_macro_rss_feeds, 'Gov RSS'),
    ]:
        try:
            items = fetcher()
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
            'items': unique_items,
        }
        cache_path.write_text(json.dumps(cache_data, indent=2))
    except Exception as e:
        print(f"  [macro_news] Cache write error: {e}")

    print(f"  [macro_news] Total: {len(unique_items)} unique items")
    return unique_items
