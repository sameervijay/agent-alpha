"""
Company Analyst Agent — LangChain version.

Per-company fundamental analyst. Autonomously fetches consensus estimates,
live prices, and company news before generating or updating an investment thesis.
"""

import json

import yfinance as yf
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model, cache_get, cache_set,
    extract_json, get_final_message,
    parse_causal_links, parse_debate_position, parse_events,
)
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a fundamental equity analyst specializing in the semiconductor value chain.
You cover: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV).

Your responsibilities:
- Develop and maintain investment theses grounded in DCF analysis
- Monitor consensus estimates and identify where your model diverges from the Street
- Detect material news events and map them to specific DCF driver changes
- Participate in multi-analyst debates to sharpen conviction

When you need data from multiple sources, call multiple tools in parallel in a single step.
Use your tools to fetch company-specific data before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_company_price_and_financials(ticker: str) -> str:
    """Get current price, 52-week range, P/E, and recent earnings info for a ticker."""
    key = f"company_financials:{ticker}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        t = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period='1y')
        result = {
            'ticker': ticker,
            'price': round(float(hist['Close'].iloc[-1]), 2) if not hist.empty else None,
            '52w_high': round(float(hist['High'].max()), 2) if not hist.empty else None,
            '52w_low': round(float(hist['Low'].min()), 2) if not hist.empty else None,
            'pe_ratio': info.get('trailingPE'),
            'forward_pe': info.get('forwardPE'),
            'market_cap_b': round(info.get('marketCap', 0) / 1e9, 1),
            'revenue_growth_yoy': info.get('revenueGrowth'),
            'gross_margin': info.get('grossMargins'),
            'operating_margin': info.get('operatingMargins'),
        }
        out = json.dumps(result, indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"Financials fetch error for {ticker}: {e}"


@tool
def get_consensus_estimates(ticker: str) -> str:
    """Read analyst consensus revenue, earnings, and valuation data from the company's Google Sheet.

    Returns financials (revenue, EBITDA, EPS for FY2026/FY2027), current multiples,
    implied share prices, and the analyst's prior thesis/conviction from the
    Agent View and Agent Documentation tabs.
    """
    key = f"consensus:{ticker}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        from sheets_client import load_analyst_view
        view = load_analyst_view(ticker)
        if view:
            out = json.dumps(view, indent=2, default=str)
            cache_set(key, out)
            return out
        return f"No Google Sheet data found for {ticker}."
    except Exception as e:
        return f"Google Sheets read error for {ticker}: {e}"


@tool
def fetch_company_news(ticker: str) -> str:
    """Fetch recent news articles specifically about a company (by ticker or company name)."""
    key = f"company_news:{ticker}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
        out = json.dumps([{
            'headline': n.get('title', ''),
            'publisher': n.get('publisher', ''),
            'link': n.get('link', ''),
            'published': n.get('providerPublishTime', ''),
        } for n in news[:10]], indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        # Fallback to macro news fetcher filtered by ticker
        try:
            articles = cache_get("macro_news_raw")
            if articles is None:
                from tools.macro_news_fetcher import fetch_all_macro_news
                articles = fetch_all_macro_news(max_items=40)
                cache_set("macro_news_raw", articles)
            ticker_map = {
                'NVDA': 'nvidia', 'TSM': 'tsmc', 'ASML': 'asml',
                'CDNS': 'cadence', 'CRWV': 'coreweave',
            }
            keyword = ticker_map.get(ticker.upper(), ticker.lower())
            relevant = [a for a in articles
                        if keyword in a.get('headline', '').lower()
                        or keyword in a.get('summary', '').lower()]
            out = json.dumps([{
                'headline': a.get('headline', ''),
                'summary': a.get('summary', '')[:200],
                'source': a.get('source', ''),
                'date': a.get('date', ''),
            } for a in relevant[:8]], indent=2)
            cache_set(key, out)
            return out
        except Exception as e2:
            return f"News fetch error for {ticker}: {e2}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class CompanyAnalystAgent:
    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        self.name = f"analyst_{self.ticker.lower()}"
        self.role_description = f"Fundamental Analyst — {self.ticker}"
        self._agent = create_agent(
            build_model(),
            tools=[get_company_price_and_financials, get_consensus_estimates,
                   fetch_company_news],
            system_prompt=SYSTEM_PROMPT,
        )

    def develop_thesis(self) -> dict:
        """
        Build a fresh investment thesis for self.ticker.
        Returns a dict with: thesis, bull_case, bear_case, conviction (0-1),
        key_risks, dcf_driver_adjustments.
        """
        goal = (
            f"Develop a comprehensive investment thesis for {self.ticker}.\n\n"
            f"Fetch financials, consensus estimates, and recent news for {self.ticker} in parallel.\n\n"
            "Synthesize all data into a thesis.\n\n"
            "Return a JSON object with:\n"
            "  ticker, thesis (2-3 paragraph summary), bull_case (list of 3 points), "
            "bear_case (list of 3 points), conviction (0.0-1.0), key_risks (list), "
            "dcf_driver_adjustments (dict of driver -> delta, e.g. datacenter_growth: 0.05)."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return extract_json(get_final_message(result))

    def detect_events(self, news_input: str = None) -> list:
        """Identify company-specific events from news that map to DCF driver changes."""
        goal = (
            f"Fetch recent news and financials for {self.ticker} in parallel, then identify "
            f"material events that change the fundamental outlook.\n\n"
            "Return a JSON object with key 'events'. Each event must have:\n"
            "  headline, description, affected_companies (list with just this ticker), "
            "affected_segments (list), severity (low/medium/high/critical), "
            "direction (positive/negative/neutral/mixed)."
        )
        if news_input:
            goal += f"\n\nAdditional context:\n{news_input}"

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_events(get_final_message(result), self.name, news_input or '')

    def build_causal_links(self, event: Event) -> list:
        """Trace causal chain from a company event to DCF drivers."""
        goal = (
            f"Given this event affecting {self.ticker}, trace its causal chain to DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n\n"
            "Fetch consensus estimates or financials to anchor your magnitude estimates.\n\n"
            "Return a JSON object with key 'causal_links'. Each link must have:\n"
            "  source_event, intermediate_step, downstream_metric "
            "(one of: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, "
            "oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps), "
            f"affected_company ('{self.ticker}'), affected_periods (list), "
            "direction (increase/decrease), magnitude_estimate, confidence (0.0-1.0), reasoning."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_causal_links(get_final_message(result), self.name)

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        """Provide a fundamental-analyst position in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of an event on a DCF metric for {company}.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            f"Fetch {company} consensus estimates to ground your position in data.\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_debate_position(get_final_message(result))

    def __repr__(self):
        return f"<CompanyAnalystAgent ticker={self.ticker!r} (LangChain)>"
