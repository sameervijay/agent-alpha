"""
Company Analyst Agent — LangChain version.

Per-company fundamental analyst. Autonomously fetches consensus estimates,
live prices, and company news before generating or updating an investment thesis.
"""

import json

import yfinance as yf
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import build_model, extract_json, get_final_message
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a fundamental equity analyst specializing in the semiconductor value chain.
You cover: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV).

Your responsibilities:
- Develop and maintain investment theses grounded in DCF analysis
- Monitor consensus estimates and identify where your model diverges from the Street
- Detect material news events and map them to specific DCF driver changes
- Participate in multi-analyst debates to sharpen conviction

Use your tools to fetch company-specific data before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_company_price_and_financials(ticker: str) -> str:
    """Get current price, 52-week range, P/E, and recent earnings info for a ticker."""
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
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Financials fetch error for {ticker}: {e}"


@tool
def get_consensus_estimates(ticker: str) -> str:
    """Read analyst consensus revenue and earnings estimates from the consensus Excel file for a ticker."""
    try:
        from tools.consensus_reader import ConsensusReader
        reader = ConsensusReader(ticker)
        consensus = reader.get_consensus()
        return json.dumps(consensus, indent=2, default=str)
    except FileNotFoundError:
        return f"No consensus file found for {ticker}."
    except Exception as e:
        return f"Consensus read error for {ticker}: {e}"


@tool
def fetch_company_news(ticker: str) -> str:
    """Fetch recent news articles specifically about a company (by ticker or company name)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        news = t.news or []
        return json.dumps([{
            'headline': n.get('title', ''),
            'publisher': n.get('publisher', ''),
            'link': n.get('link', ''),
            'published': n.get('providerPublishTime', ''),
        } for n in news[:10]], indent=2)
    except Exception as e:
        # Fallback to macro news fetcher filtered by ticker
        try:
            from tools.macro_news_fetcher import fetch_all_macro_news
            ticker_map = {
                'NVDA': 'nvidia', 'TSM': 'tsmc', 'ASML': 'asml',
                'CDNS': 'cadence', 'CRWV': 'coreweave',
            }
            keyword = ticker_map.get(ticker.upper(), ticker.lower())
            articles = fetch_all_macro_news(max_items=30)
            relevant = [a for a in articles
                        if keyword in a.get('headline', '').lower()
                        or keyword in a.get('summary', '').lower()]
            return json.dumps([{
                'headline': a.get('headline', ''),
                'summary': a.get('summary', '')[:200],
                'source': a.get('source', ''),
                'date': a.get('date', ''),
            } for a in relevant[:8]], indent=2)
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
            f"1. Fetch current financials and price for {self.ticker}.\n"
            f"2. Read the consensus estimates for {self.ticker}.\n"
            f"3. Fetch recent company news for {self.ticker}.\n"
            f"4. Synthesize all data into a thesis.\n\n"
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
            f"Fetch recent news and financials for {self.ticker}, then identify "
            f"material events that change the fundamental outlook.\n\n"
            "Return a JSON object with key 'events'. Each event must have:\n"
            "  headline, description, affected_companies (list with just this ticker), "
            "affected_segments (list), severity (low/medium/high/critical), "
            "direction (positive/negative/neutral/mixed)."
        )
        if news_input:
            goal += f"\n\nAdditional context:\n{news_input}"

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        data = extract_json(get_final_message(result))

        return [
            Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=self.name,
                affected_companies=e.get('affected_companies', [self.ticker]),
                affected_segments=e.get('affected_segments', []),
                severity=e['severity'],
                direction=e['direction'],
                raw_input=news_input or '',
            )
            for e in data.get('events', [])
        ]

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
        data = extract_json(get_final_message(result))

        return [
            CausalLink(
                source_event=l['source_event'],
                intermediate_step=l['intermediate_step'],
                downstream_metric=l['downstream_metric'],
                affected_company=l['affected_company'],
                affected_periods=l['affected_periods'],
                direction=l['direction'],
                magnitude_estimate=l['magnitude_estimate'],
                confidence=l['confidence'],
                reasoning=l['reasoning'],
                proposed_by=self.name,
            )
            for l in data.get('causal_links', [])
        ]

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
        return extract_json(get_final_message(result))

    def __repr__(self):
        return f"<CompanyAnalystAgent ticker={self.ticker!r} (LangChain)>"
