"""
Commodities Agent — LangChain version.

Fetches memory pricing, packaging capacity, and supply chain data autonomously
before reasoning about commodity-driven impacts on semiconductors.
"""

import json

from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model, cache_get, cache_set,
    get_final_message, parse_causal_links, parse_debate_position, parse_events,
)
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a semiconductor supply chain and commodities expert.
Your domain expertise covers:
- HBM (High Bandwidth Memory) pricing and supply constraints
- DRAM and NAND commodity pricing cycles
- Advanced packaging capacity (CoWoS, SoIC, substrates)
- Rare earth materials and specialty gases used in chip manufacturing
- Wafer supply and foundry utilization rates
- Supply chain disruptions and lead times

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

When you need data from multiple sources, call multiple tools in parallel in a single step.
Use your tools to fetch current memory pricing and packaging capacity data before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_memory_pricing_report() -> str:
    """Get the latest HBM and DRAM memory pricing trends and supply/demand signals."""
    cached = cache_get("memory_pricing_report")
    if cached:
        return cached
    try:
        from tools.memory_pricing_monitor import generate_weekly_memory_report
        report = generate_weekly_memory_report(days_back=7)
        out = report[:2500] if len(report) > 2500 else report
        cache_set("memory_pricing_report", out)
        return out
    except Exception as e:
        return f"Memory pricing error: {e}"


@tool
def get_packaging_capacity_report() -> str:
    """Get current advanced packaging capacity (CoWoS, substrates, HBM constraints) from industry sources."""
    cached = cache_get("packaging_capacity_report")
    if cached:
        return cached
    try:
        from tools.advanced_packaging_monitor import generate_packaging_monitoring_report
        report = generate_packaging_monitoring_report()
        out = report[:2500] if len(report) > 2500 else report
        cache_set("packaging_capacity_report", out)
        return out
    except Exception as e:
        return f"Packaging capacity error: {e}"


@tool
def fetch_supply_chain_news(query: str) -> str:
    """Fetch recent news about semiconductor supply chain, commodities, or materials matching the query."""
    try:
        articles = cache_get("macro_news_raw")
        if articles is None:
            from tools.macro_news_fetcher import fetch_all_macro_news
            articles = fetch_all_macro_news(max_items=40)
            cache_set("macro_news_raw", articles)

        supply_keywords = {
            'hbm', 'dram', 'nand', 'memory', 'wafer', 'substrate',
            'packaging', 'cowos', 'supply chain', 'shortage', 'lead time',
            'capacity', 'utilization', 'samsung', 'sk hynix', 'micron',
        }
        q = query.lower()
        relevant = [
            a for a in articles
            if q in a.get('headline', '').lower()
            or q in a.get('summary', '').lower()
            or any(kw in a.get('headline', '').lower() for kw in supply_keywords)
        ]
        subset = relevant[:8] if relevant else articles[:5]
        return json.dumps([{
            'headline': a.get('headline', ''),
            'summary': a.get('summary', '')[:300],
            'source': a.get('source', ''),
            'date': a.get('date', ''),
        } for a in subset], indent=2)
    except Exception as e:
        return f"Supply chain news error: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class CommoditiesAgent:
    def __init__(self):
        self.name = "commodities_agent"
        self.role_description = "Supply Chain & Commodities Expert"
        self._agent = create_agent(
            build_model(),
            tools=[get_memory_pricing_report, get_packaging_capacity_report,
                   fetch_supply_chain_news],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch supply chain data autonomously and identify commodity-driven events."""
        goal = (
            "Fetch the memory pricing report, packaging capacity data, and supply chain news "
            "in parallel (call all three tools simultaneously). "
            "Then identify commodity and supply chain events that materially affect semiconductor companies "
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
        """Trace causal chain from a commodity event to DCF drivers."""
        goal = (
            f"Given this supply chain / commodity event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "Fetch memory pricing or packaging capacity data to quantify the impact.\n\n"
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
        """Provide a commodities/supply-chain perspective in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of a supply chain event on a financial metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            "Fetch relevant memory or packaging data if it strengthens your argument.\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_debate_position(get_final_message(result))

    def __repr__(self):
        return f"<CommoditiesAgent (LangChain)>"
