"""
Stock Market Agent — LangChain version.

Fetches live prices, market snapshots, and unusual volume signals autonomously
before reasoning about equity market impacts on semiconductors.
"""

import json
from datetime import datetime

import yfinance as yf
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model, cache_get, cache_set,
    get_final_message, parse_causal_links, parse_debate_position, parse_events,
)
from models.event import Event
from models.causal_graph import CausalLink

TICKERS = ['NVDA', 'TSM', 'ASML', 'CDNS', 'CRWV']

SYSTEM_PROMPT = """You are an equity markets expert specializing in semiconductor stocks.
Your domain expertise covers:
- Stock price movements, trading volumes, and momentum
- Sell-side analyst ratings, price targets, and consensus estimates
- Sector rotation patterns (growth vs value, tech vs cyclicals)
- Institutional positioning and fund flows
- Earnings revisions and estimate momentum
- Relative valuation (P/E, EV/EBITDA) across the semiconductor value chain

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

DATA SOURCE PRIORITY (highest to lowest):
1. get_stock_prices() — live yfinance price data (primary)
2. get_market_snapshot() — structured market monitor (primary)
3. detect_unusual_volumes() — structured volume analysis (primary)
4. search_web_market_news() — real-time web search (SUPPLEMENTARY ONLY)

Web search results are lower-confidence signals. Use them to surface breaking news
(analyst upgrades, earnings surprises, institutional filings) not yet reflected in
price/volume data. Never override live price data with web search findings.
Note when a finding comes from web search vs. live market data.

When you need data from multiple sources, call multiple tools in parallel in a single step.
Use your tools to fetch live prices and market data before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_stock_prices(tickers: str) -> str:
    """Get current prices and 5-day/30-day returns for a comma-separated list of tickers."""
    key = f"stock_prices:{tickers}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        result = {}
        for ticker in [t.strip() for t in tickers.split(',')]:
            hist = yf.Ticker(ticker).history(period='1mo')
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
                result[ticker] = {
                    'price': round(price, 2),
                    'return_5d_pct': round(
                        (hist['Close'].iloc[-1] / hist['Close'].iloc[-5] - 1) * 100, 2
                    ) if len(hist) >= 5 else None,
                    'return_30d_pct': round(
                        (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100, 2
                    ),
                    'avg_volume_30d': int(hist['Volume'].mean()),
                    'latest_volume': int(hist['Volume'].iloc[-1]),
                }
        out = json.dumps(result, indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"Price fetch error: {e}"


@tool
def get_market_snapshot() -> str:
    """Get a snapshot of the semiconductor market: prices, volumes, and sector ETF performance."""
    cached = cache_get("market_snapshot")
    if cached:
        return cached
    try:
        from tools.market_monitor import MarketMonitor
        monitor = MarketMonitor()
        snapshot = monitor.get_market_snapshot()
        out = json.dumps(snapshot, indent=2, default=str)
        cache_set("market_snapshot", out)
        return out
    except Exception as e:
        # Fallback: pull prices directly
        return get_stock_prices.invoke(','.join(TICKERS))


@tool
def detect_unusual_volumes() -> str:
    """Detect unusual trading volumes or price movements in semiconductor stocks today."""
    cached = cache_get("unusual_volumes")
    if cached:
        return cached
    try:
        from tools.market_monitor import MarketMonitor
        monitor = MarketMonitor()
        unusual = monitor.detect_unusual_volumes()
        out = json.dumps(unusual, indent=2, default=str)
        cache_set("unusual_volumes", out)
        return out
    except Exception as e:
        return f"Volume detection error: {e}"


@tool
def search_web_market_news(query: str) -> str:
    """Search the web for real-time breaking equity market news relevant to semiconductor stocks:
    analyst upgrades/downgrades, price target changes, institutional filings (13F/13G),
    earnings pre-announcements, short interest changes, sector fund flows.
    SUPPLEMENTARY ONLY — lower confidence than live yfinance price and volume data.
    Use to explain price moves already visible in structured data, not to replace it."""
    cache_key = f"tavily_market:{query.lower()[:60]}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        from tools.tavily_search import tavily_search, format_tavily_results
        results = tavily_search(query, max_results=5)
        out = format_tavily_results(results)
        cache_set(cache_key, out)
        return out
    except Exception as e:
        return f"Web search unavailable: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class StockMarketAgent:
    def __init__(self):
        self.name = "stock_market_agent"
        self.role_description = "Equity Markets & Analyst Consensus Expert"
        self._agent = create_agent(
            build_model(),
            tools=[get_stock_prices, get_market_snapshot, detect_unusual_volumes,
                   search_web_market_news],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch market data autonomously and identify equity market events."""
        goal = (
            "Fetch semiconductor equity market intelligence in parallel:\n"
            "  1. get_stock_prices('NVDA,TSM,ASML,CDNS,CRWV') — live prices (primary)\n"
            "  2. get_market_snapshot() — structured market monitor (primary)\n"
            "  3. detect_unusual_volumes() — volume analysis (primary)\n"
            "  4. search_web_market_news('NVIDIA TSMC ASML analyst upgrade downgrade 2025') — web (supplementary)\n"
            "  5. search_web_market_news('semiconductor stocks institutional investors fund flows') — web (supplementary)\n\n"
            "DATA PRIORITY: Live market data (1-3) > web search (4-5).\n"
            "Web search is supplementary — use to explain price moves or surface analyst actions "
            "not yet reflected in price/volume data. Do not override live data with web results.\n"
            "Identify significant equity market events (large moves, unusual activity, "
            "sector rotation, valuation dislocations, analyst rating changes).\n\n"
            "Return a JSON object with key 'events'. Each event must have:\n"
            "  headline, description, affected_companies (list of tickers), "
            "affected_segments (list), severity (low/medium/high/critical), "
            "direction (positive/negative/neutral/mixed)."
        )
        if news_input:
            goal += f"\n\nAlso consider this pre-fetched context:\n{news_input}"

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_events(get_final_message(result), self.name, news_input or '')

    def build_causal_links(self, event: Event) -> list:
        """Trace causal chain from a market event to DCF drivers."""
        goal = (
            f"Given this stock market event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "Fetch current prices to check how the market has already reacted.\n\n"
            "Return a JSON object with key 'causal_links'. Each link must have:\n"
            "  source_event, intermediate_step, downstream_metric "
            "(one of: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, "
            "oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps), "
            "affected_company (ticker), affected_periods (list), direction (increase/decrease), "
            "magnitude_estimate, confidence (0.0-1.0), reasoning."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_causal_links(get_final_message(result), self.name)

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        """Provide an equity-markets perspective in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of a market event on a financial metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            f"You may fetch {company} current price data to support your position.\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_debate_position(get_final_message(result))

    def get_current_prices(self, tickers: list) -> dict:
        """Fetch live prices for a list of tickers. Returns {ticker: {price, prev_close, change_pct, ...}}."""
        results = {}
        for ticker in tickers:
            try:
                hist = yf.Ticker(ticker).history(period='5d')
                if hist.empty:
                    results[ticker] = {'price': 0.0, 'prev_close': 0.0, 'change_pct': 0.0,
                                        'timestamp': datetime.now().isoformat(), 'error': 'No data'}
                    continue
                price = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else price
                change_pct = (price / prev - 1) if prev and prev > 0 else 0.0
                results[ticker] = {
                    'price': round(price, 2),
                    'prev_close': round(prev, 2),
                    'change_pct': change_pct,
                    'timestamp': datetime.now().isoformat(),
                    'error': None,
                }
            except Exception as e:
                results[ticker] = {'price': 0.0, 'prev_close': 0.0, 'change_pct': 0.0,
                                  'timestamp': datetime.now().isoformat(), 'error': str(e)}
        return results

    def get_price(self, ticker: str, use_cache: bool = True, cache_ttl_seconds: int = 300) -> float:
        """Get current price for a single ticker (for DCF engines). Returns 0.0 if unavailable."""
        key = f"stock_prices:{ticker}"
        if use_cache and cache_get(key):
            try:
                data = json.loads(cache_get(key))
                return float(data.get(ticker, {}).get('price', 0.0))
            except (TypeError, json.JSONDecodeError, KeyError):
                pass
        try:
            hist = yf.Ticker(ticker).history(period='5d')
            if hist.empty:
                return 0.0
            price = float(hist['Close'].iloc[-1])
            cache_set(key, json.dumps({ticker: {'price': round(price, 2)}}))
            return price
        except Exception:
            return 0.0

    def get_market_snapshot(self) -> dict:
        """Get market snapshot dict (tickers, prices, timestamp, summary) for tests/compatibility."""
        try:
            import config
            tickers = list(config.COMPANIES.keys()) + ['SPY']
        except Exception:
            tickers = list(TICKERS) + ['SPY']
        prices = self.get_current_prices(tickers)
        num_up = sum(1 for p in prices.values() if p.get('change_pct', 0) > 0)
        num_down = sum(1 for p in prices.values() if p.get('change_pct', 0) < 0)
        summary = (f"Market snapshot: {num_up} up, {num_down} down. "
                   f"SPY: ${prices.get('SPY', {}).get('price', 0):.2f}")
        return {
            'tickers': tickers,
            'prices': prices,
            'timestamp': datetime.now().isoformat(),
            'summary': summary,
        }

    def __repr__(self):
        return f"<StockMarketAgent (LangChain)>"
