"""
Macro Economics Agent — LangChain version.

The LLM autonomously fetches macro news and interest-rate data via tools
before reasoning about semiconductor market impacts.
"""

import json

import yfinance as yf
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model, cache_get, cache_set,
    get_final_message, parse_causal_links, parse_debate_position, parse_events,
)
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a macroeconomics expert analyzing how economic conditions affect the semiconductor industry.
Your domain expertise covers:
- Federal Reserve policy (fed funds rate, quantitative tightening/easing)
- Treasury yields (2Y, 10Y) and the yield curve
- GDP growth and economic cycle positioning
- Inflation (CPI, PPI, PCE) and its impact on tech spending
- Corporate capex cycles and IT budget trends
- Currency movements (USD/TWD, USD/EUR, USD/JPY) and their impact on semiconductor companies
- Consumer spending and confidence indicators
- Data center capex trends from hyperscalers (AWS, Azure, GCP)

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

When you need data from multiple sources, call multiple tools in parallel in a single step.
Use your tools to fetch current macro news and market data before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def fetch_macro_news(query: str) -> str:
    """Fetch recent macro economic news articles matching the query (e.g. 'Fed rates', 'inflation', 'GDP')."""
    try:
        # Reuse the raw article list fetched earlier in this session
        articles = cache_get("macro_news_raw")
        if articles is None:
            from tools.macro_news_fetcher import fetch_all_macro_news
            articles = fetch_all_macro_news(max_items=40)
            cache_set("macro_news_raw", articles)

        q = query.lower()
        relevant = [a for a in articles
                    if q in a.get('headline', '').lower()
                    or q in a.get('summary', '').lower()]
        subset = relevant[:8] if relevant else articles[:5]
        return json.dumps([{
            'headline': a.get('headline', ''),
            'summary': a.get('summary', '')[:300],
            'source': a.get('source', ''),
            'date': a.get('date', ''),
        } for a in subset], indent=2)
    except Exception as e:
        return f"News fetch error: {e}"


@tool
def get_treasury_yields() -> str:
    """Fetch current US Treasury yields (2Y, 10Y, 30Y) and the Fed funds rate proxy."""
    cached = cache_get("treasury_yields")
    if cached:
        return cached
    try:
        tickers = {
            '2Y_yield': '^IRX',
            '10Y_yield': '^TNX',
            '30Y_yield': '^TYX',
        }
        result = {}
        for label, sym in tickers.items():
            t = yf.Ticker(sym)
            hist = t.history(period='5d')
            if not hist.empty:
                result[label] = round(float(hist['Close'].iloc[-1]), 3)
        out = json.dumps(result)
        cache_set("treasury_yields", out)
        return out
    except Exception as e:
        return f"Yield fetch error: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class MacroAgent:
    def __init__(self):
        self.name = "macro_agent"
        self.role_description = "Macroeconomics & Interest Rate Expert"
        self._agent = create_agent(
            build_model(),
            tools=[fetch_macro_news, get_treasury_yields],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch news autonomously and return a list of Event objects."""
        goal = (
            "Fetch relevant macro news (Fed policy, yields, inflation, GDP, capex cycles) "
            "and treasury yields in parallel, "
            "then identify macroeconomic events that affect semiconductor companies "
            "(NVDA, TSM, ASML, CDNS, CRWV).\n\n"
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
        """Trace causal chain from a macro event to DCF drivers."""
        goal = (
            f"Given this macro event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "You may fetch current yield or news data to strengthen your analysis.\n\n"
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
        """Provide a macro-perspective position in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of a macro event on a financial metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_debate_position(get_final_message(result))

    def __repr__(self):
        return f"<MacroAgent (LangChain)>"
