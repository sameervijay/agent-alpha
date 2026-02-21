"""
Geopolitics Agent — LangChain version.

Fetches geopolitics and trade-policy news autonomously before reasoning
about impacts on the semiconductor value chain.
"""

import json

from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import build_model, extract_json, get_final_message
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a geopolitics expert specializing in the semiconductor industry.
Your domain expertise covers:
- US-China trade relations and technology competition
- Export controls (Bureau of Industry and Security, Entity List)
- CHIPS Act and semiconductor subsidies (US, EU, Japan, India)
- Taiwan Strait geopolitical risk and its impact on TSMC
- Sanctions regimes and their second-order effects on the semiconductor value chain

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

Use your tools to fetch current geopolitics and trade-policy news before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def fetch_geopolitics_news(query: str) -> str:
    """Fetch recent news about geopolitics, trade policy, export controls, or sanctions matching the query."""
    try:
        from tools.macro_news_fetcher import fetch_all_macro_news
        articles = fetch_all_macro_news(max_items=30)
        geo_keywords = {'china', 'taiwan', 'export', 'sanction', 'chips act',
                        'trade', 'tariff', 'entity list', 'bis', 'geopolit'}
        q = query.lower()
        relevant = [
            a for a in articles
            if q in a.get('headline', '').lower()
            or q in a.get('summary', '').lower()
            or any(kw in a.get('headline', '').lower() for kw in geo_keywords)
        ]
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
def get_affected_stock_prices(tickers: str) -> str:
    """Get current stock prices for a comma-separated list of tickers (e.g. 'NVDA,TSM,ASML')."""
    try:
        import yfinance as yf
        result = {}
        for ticker in [t.strip() for t in tickers.split(',')]:
            hist = yf.Ticker(ticker).history(period='5d')
            if not hist.empty:
                result[ticker] = {
                    'price': round(float(hist['Close'].iloc[-1]), 2),
                    'change_pct_5d': round(
                        (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100, 2
                    ),
                }
        return json.dumps(result)
    except Exception as e:
        return f"Price fetch error: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class PoliticsAgent:
    def __init__(self):
        self.name = "politics_agent"
        self.role_description = "Geopolitics & Regulatory Expert"
        self._agent = create_agent(
            build_model(),
            tools=[fetch_geopolitics_news, get_affected_stock_prices],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch geopolitics news autonomously and return a list of Event objects."""
        goal = (
            "Fetch recent geopolitics and trade-policy news (US-China tensions, export controls, "
            "CHIPS Act, Taiwan risk, sanctions), then identify events that affect semiconductor companies "
            "(NVDA, TSM, ASML, CDNS, CRWV).\n\n"
            "Return a JSON object with key 'events'. Each event must have:\n"
            "  headline, description, affected_companies (list of tickers), "
            "affected_segments (list), severity (low/medium/high/critical), "
            "direction (positive/negative/neutral/mixed)."
        )
        if news_input:
            goal += f"\n\nAlso consider this pre-fetched context:\n{news_input}"

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        data = extract_json(get_final_message(result))

        return [
            Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=self.name,
                affected_companies=e.get('affected_companies', []),
                affected_segments=e.get('affected_segments', []),
                severity=e['severity'],
                direction=e['direction'],
                raw_input=news_input or '',
            )
            for e in data.get('events', [])
        ]

    def build_causal_links(self, event: Event) -> list:
        """Trace causal chain from a geopolitical event to DCF drivers."""
        goal = (
            f"Given this geopolitical event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "You may check affected stock prices to gauge market reaction.\n\n"
            "Return a JSON object with key 'causal_links'. Each link must have:\n"
            "  source_event, intermediate_step, downstream_metric "
            "(one of: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, "
            "oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps), "
            "affected_company (ticker), affected_periods (list), direction (increase/decrease), "
            "magnitude_estimate, confidence (0.0-1.0), reasoning."
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
        """Provide a geopolitics-perspective position in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of a geopolitical event on a financial metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return extract_json(get_final_message(result))

    def __repr__(self):
        return f"<PoliticsAgent (LangChain)>"
