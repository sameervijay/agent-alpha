"""
Tavily web search wrapper for domain scout agents.

Results are SUPPLEMENTARY context — lower confidence than structured data sources
(FRED, yfinance, Federal Register, SEC EDGAR, etc.).  Agents should use these to
corroborate or extend structured signals, never to override them.
"""

import json
import os


def tavily_search(query: str, max_results: int = 5) -> list:
    """
    Search the web via Tavily and return structured results.

    Each result dict:
        headline    : article title
        url         : source URL
        date        : published date (may be empty)
        source      : domain name extracted from URL
        summary     : first 400 chars of content
        reliability : always "web_search_supplementary" — agents must weight
                      these below structured data (FRED, yfinance, SEC, etc.)

    Returns [] if TAVILY_API_KEY is not set or on any error.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        # Try importing config — but don't fail if unavailable
        try:
            import config
            api_key = getattr(config, "TAVILY_API_KEY", "")
        except ImportError:
            pass

    if not api_key:
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
        )
        results = []
        for r in response.get("results", []):
            url = r.get("url", "")
            # Extract bare domain for source field
            try:
                domain = url.split("/")[2]
            except IndexError:
                domain = url
            results.append({
                "headline": r.get("title", ""),
                "url": url,
                "date": r.get("published_date", ""),
                "source": domain,
                "summary": (r.get("content", "") or "")[:400],
                "reliability": "web_search_supplementary",
            })

        # Log results so the caller can see what Tavily returned
        print(f"    [Tavily] query='{query}' → {len(results)} result(s)")
        for i, r in enumerate(results, 1):
            date_str = f" ({r['date'][:10]})" if r.get("date") else ""
            print(f"      {i}. [{r['source']}]{date_str} {r['headline'][:90]}")

        return results
    except Exception as e:
        print(f"    [Tavily] query='{query}' → error: {e}")
        return []


def format_tavily_results(results: list) -> str:
    """Serialize Tavily results to a JSON string for agent tool return values."""
    if not results:
        return json.dumps([], indent=2)
    return json.dumps(results, indent=2)
