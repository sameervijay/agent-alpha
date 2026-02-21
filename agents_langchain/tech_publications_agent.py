"""
Tech Publications Agent — LangChain version.

Fetches semiconductor technology and R&D news from industry publications
autonomously before reasoning about technology-driven impacts.
"""

import json

from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import build_model, extract_json, get_final_message
from models.event import Event
from models.causal_graph import CausalLink

TECH_KEYWORDS = {
    'process node', 'angstrom', 'euv', 'asml', 'tsmc', 'gate-all-around',
    'gaa', 'backside power', 'chiplet', 'packaging', 'hbm', 'bandwidth',
    'nvidia', 'blackwell', 'hopper', 'cuda', 'architecture', 'foundry',
    'yield', 'wafer', 'lithography', 'cadence', 'synopsys', 'eda',
}

SYSTEM_PROMPT = """You are a semiconductor technology expert tracking industry publications and R&D advances.
Your domain expertise covers:
- Process node roadmaps (TSMC N2, Intel 18A, Samsung SF2)
- New chip architectures (NVIDIA Blackwell/Rubin, AMD MI-series)
- Advanced packaging (CoWoS, SoIC, FOVEROS)
- EDA software advances and their impact on design cycles
- HBM and memory technology trends
- Semiconductor equipment innovations (EUV, High-NA)

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

Use your tools to fetch current technology news before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def fetch_tech_news(query: str) -> str:
    """Fetch recent semiconductor technology news from industry publications matching the query."""
    try:
        from tools.macro_news_fetcher import fetch_all_macro_news
        articles = fetch_all_macro_news(max_items=40)
        q = query.lower()
        relevant = [
            a for a in articles
            if q in a.get('headline', '').lower()
            or q in a.get('summary', '').lower()
            or any(kw in a.get('headline', '').lower() for kw in TECH_KEYWORDS)
        ]
        subset = relevant[:8] if relevant else articles[:5]
        return json.dumps([{
            'headline': a.get('headline', ''),
            'summary': a.get('summary', '')[:300],
            'source': a.get('source', ''),
            'date': a.get('date', ''),
        } for a in subset], indent=2)
    except Exception as e:
        return f"Tech news fetch error: {e}"


@tool
def get_packaging_capacity_data() -> str:
    """Get current advanced packaging capacity data (CoWoS, substrates, HBM constraints)."""
    try:
        from tools.advanced_packaging_monitor import generate_packaging_monitoring_report
        report = generate_packaging_monitoring_report()
        return report[:2000] if len(report) > 2000 else report
    except Exception as e:
        return f"Packaging data error: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class TechPublicationsAgent:
    def __init__(self):
        self.name = "tech_publications_agent"
        self.role_description = "Semiconductor Technology & R&D Expert"
        self._agent = create_agent(
            build_model(),
            tools=[fetch_tech_news, get_packaging_capacity_data],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch tech news autonomously and identify technology-driven events."""
        goal = (
            "Fetch recent semiconductor technology news (process nodes, chip architectures, "
            "packaging advances, EDA tools, HBM, lithography). "
            "Then identify technology events that materially affect semiconductor companies "
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
        """Trace causal chain from a technology event to DCF drivers."""
        goal = (
            f"Given this technology event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "You may fetch packaging capacity data to support your analysis.\n\n"
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
        """Provide a technology-perspective position in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of a technology event on a financial metric.\n\n"
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
        return f"<TechPublicationsAgent (LangChain)>"
