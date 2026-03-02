"""
Geopolitics Agent — LangChain version.

Specializes in semiconductor-specific trade policy signals:
  - BIS Entity List additions / Export Administration Regulations changes
  - CHIPS Act disbursements and fab incentive announcements
  - Taiwan Strait risk escalation / TSMC supply-chain threat
  - US-China advanced-node technology competition

Uses the free Federal Register API (no key required) for authoritative
government notices, plus the general news feed filtered to semi-policy.
"""

import json

import requests
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model, cache_get, cache_set,
    get_final_message, parse_causal_links, parse_debate_position, parse_events,
)
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a semiconductor trade-policy analyst.
Your job is to surface POLICY-LEVEL SURPRISES — new developments that change the
regulatory or geopolitical backdrop for the semiconductor value chain.

Focus areas (in priority order):
1. Export control changes: BIS Entity List additions, new EAR rules restricting advanced
   semiconductor equipment or chips (especially EUV, HBM, A100/H100-class GPUs)
2. CHIPS Act disbursements: US, EU, Japan or India fab-incentive announcements that
   accelerate or delay TSMC/Samsung/Intel expansion plans
3. Taiwan Strait risk: PLA military exercises, US-Taiwan arms sales, cross-strait
   diplomatic incidents that raise TSMC supply-chain disruption probability
4. Chinese IC self-sufficiency: CXMT/YMTC/SMIC production milestones, Huawei chip
   announcements, Chinese government semiconductor investment announcements

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

IMPORTANT: Only surface events with direct, specific impact on these companies.
Do NOT report generic geopolitical background (summits, tariffs on other sectors,
general US-China trade tension) unless it has a concrete semiconductor-specific mechanism.

When you need data from multiple sources, call multiple tools in parallel in a single step.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def fetch_export_control_notices(query: str = "semiconductor export controls") -> str:
    """Search the Federal Register for recent BIS/Commerce export control and CHIPS Act notices.
    Covers Entity List updates, EAR rule changes, fab incentive announcements.
    No API key required. Examples: 'semiconductor export controls', 'chips act', 'entity list'."""
    cache_key = f"federal_register:{query}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        # Federal Register public API — no authentication required
        url = "https://www.federalregister.gov/api/v1/articles.json"
        params = {
            "fields[]": ["title", "publication_date", "abstract", "agencies", "html_url"],
            "search_term": query,
            "per_page": 8,
            "order": "newest",
            # Focus on agencies that publish semiconductor policy
            "conditions[agencies][]": [
                "commerce-department",
                "industry-and-security-bureau",
                "national-institute-of-standards-and-technology",
            ],
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("results", []):
            agencies = [a.get("name", "") for a in (item.get("agencies") or [])]
            results.append({
                "title": item.get("title", ""),
                "date": item.get("publication_date", ""),
                "agency": ", ".join(agencies),
                "abstract": (item.get("abstract") or "")[:300],
                "url": item.get("html_url", ""),
            })
        if not results:
            # Broaden if narrow query returned nothing
            params.pop("conditions[agencies][]", None)
            resp2 = requests.get(url, params=params, timeout=10)
            resp2.raise_for_status()
            data2 = resp2.json()
            for item in data2.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "date": item.get("publication_date", ""),
                    "abstract": (item.get("abstract") or "")[:300],
                })
        out = json.dumps(results[:8], indent=2)
        cache_set(cache_key, out)
        return out
    except Exception as e:
        return f"Federal Register fetch error: {e}"


@tool
def fetch_semiconductor_policy_news(query: str) -> str:
    """Search general news feed for semiconductor-specific trade policy, export controls,
    CHIPS Act, Taiwan risk, or Chinese IC self-sufficiency. Use targeted queries like
    'entity list nvidia', 'chips act tsmc', 'taiwan strait tsmc', 'huawei chip'."""
    try:
        articles = cache_get("macro_news_raw")
        if articles is None:
            from tools.macro_news_fetcher import fetch_all_macro_news
            articles = fetch_all_macro_news(max_items=40)
            cache_set("macro_news_raw", articles)

        # Semiconductor-policy-specific keywords — no generic trade/tariff noise
        semi_policy_keywords = {
            'entity list', 'export control', 'ear ', 'bis ', 'chips act',
            'taiwan strait', 'tsmc geopolit', 'advanced node', 'huawei chip',
            'hbm', 'euv export', 'semiconductor subsid', 'fab incentive',
            'cxmt', 'ymtc', 'smic', 'chinese chip', 'ic self-suffic',
        }
        q_tokens = set(query.lower().split())
        relevant = [
            a for a in articles
            if any(kw in a.get('headline', '').lower() or kw in a.get('summary', '').lower()
                   for kw in (semi_policy_keywords | q_tokens))
        ]
        subset = relevant[:8] if relevant else []
        return json.dumps([{
            'headline': a.get('headline', ''),
            'summary': a.get('summary', '')[:300],
            'source': a.get('source', ''),
            'date': a.get('date', ''),
        } for a in subset], indent=2)
    except Exception as e:
        return f"News fetch error: {e}"


@tool
def get_taiwan_strait_risk_indicators() -> str:
    """Get current Taiwan Strait risk proxy: TSMC stock vs. SPY divergence, USD/TWD rate,
    and recent PLA activity headlines. Used to quantify geopolitical risk premium."""
    cached = cache_get("taiwan_risk")
    if cached:
        return cached
    try:
        import yfinance as yf
        result = {}

        # USD/TWD — a weakening TWD signals risk-off re Taiwan
        twd = yf.Ticker("TWD=X").history(period="5d")
        if not twd.empty:
            result["usd_twd"] = {
                "current": round(float(twd["Close"].iloc[-1]), 4),
                "5d_change_pct": round(
                    (twd["Close"].iloc[-1] / twd["Close"].iloc[0] - 1) * 100, 2
                ),
                "note": "rising USD/TWD = TWD weakening = risk-off re Taiwan",
            }

        # TSMC ADR vs. SPY divergence (last 5 days)
        for sym, label in [("TSM", "tsm_adr"), ("^GSPC", "spx")]:
            hist = yf.Ticker(sym).history(period="5d")
            if not hist.empty:
                result[label] = {
                    "5d_return_pct": round(
                        (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 2
                    ),
                }
        if "tsm_adr" in result and "spx" in result:
            result["tsm_vs_spx_spread_pp"] = round(
                result["tsm_adr"]["5d_return_pct"] - result["spx"]["5d_return_pct"], 2
            )

        out = json.dumps(result, indent=2)
        cache_set("taiwan_risk", out)
        return out
    except Exception as e:
        return f"Taiwan risk fetch error: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class PoliticsAgent:
    def __init__(self):
        self.name = "politics_agent"
        self.role_description = "Semiconductor Trade Policy & Geopolitics Expert"
        self._agent = create_agent(
            build_model(),
            tools=[
                fetch_export_control_notices,
                fetch_semiconductor_policy_news,
                get_taiwan_strait_risk_indicators,
            ],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch semiconductor trade-policy signals and return a list of Event objects."""
        if news_input:
            # Event-conditional: anchor on the injected event first, then sweep for policy amplifiers
            goal = (
                f"The following market event has just occurred:\n{news_input}\n\n"
                "Your task: identify GEOPOLITICAL AND REGULATORY FORCES that amplify or dampen "
                "this event's impact on NVDA, TSM, ASML, CDNS, CRWV.\n\n"
                "Search in parallel for:\n"
                "1. Recent Federal Register notices on export controls or CHIPS Act (use "
                "   fetch_export_control_notices with relevant queries)\n"
                "2. Semiconductor-specific policy news (entity list, Taiwan risk, Chinese IC "
                "   self-sufficiency — use fetch_semiconductor_policy_news)\n"
                "3. Taiwan Strait risk indicators (use get_taiwan_strait_risk_indicators)\n\n"
                "Only report events with a CONCRETE mechanism linking them to the affected companies. "
                "Skip generic geopolitical background noise.\n\n"
                "Return a JSON object with key 'events'. Each event must have:\n"
                "  headline, description, affected_companies (list of tickers), "
                "affected_segments (list), severity (low/medium/high/critical), "
                "direction (positive/negative/neutral/mixed)."
            )
        else:
            goal = (
                "Sweep for fresh semiconductor trade-policy signals. Search in parallel for:\n"
                "1. Recent Federal Register export control and CHIPS Act notices\n"
                "2. Entity List additions, EAR rule changes, Taiwan risk, Chinese IC news\n"
                "3. Taiwan Strait risk indicators\n\n"
                "Only surface events with a direct mechanism affecting NVDA, TSM, ASML, CDNS, or CRWV. "
                "Skip generic trade/tariff/summit noise.\n\n"
                "Return a JSON object with key 'events'. Each event must have:\n"
                "  headline, description, affected_companies (list of tickers), "
                "affected_segments (list), severity (low/medium/high/critical), "
                "direction (positive/negative/neutral/mixed)."
            )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_events(get_final_message(result), self.name, news_input or '')

    def build_causal_links(self, event: Event) -> list:
        """Trace causal chain from a geopolitical event to DCF drivers."""
        goal = (
            f"Given this geopolitical/regulatory event, trace its causal chain to semiconductor "
            f"DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "Fetch Taiwan Strait risk indicators and any relevant export control notices "
            "to anchor your magnitude estimates.\n\n"
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
        """Provide a trade-policy perspective in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the regulatory/geopolitical impact of an event on a DCF metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            "Fetch Taiwan Strait risk indicators to ground your position in current data.\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_debate_position(get_final_message(result))

    def __repr__(self):
        return f"<PoliticsAgent (LangChain)>"
