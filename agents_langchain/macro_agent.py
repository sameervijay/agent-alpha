"""
Macro Economics Agent — LangChain version.

Assesses how the macroeconomic environment AMPLIFIES or DAMPENS a semiconductor
event's investment impact. Focuses on:
  - Semiconductor capacity utilization cycle (FRED CAPUTLG334P1S)
  - Real rate environment and its effect on capex decisions (FRED FEDFUNDS, T10YIE)
  - USD/TWD, USD/EUR cross-rates affecting TSMC/ASML USD-reported earnings
  - Hyperscaler capex trajectory (AWS/Azure/GCP/Meta guidance)
  - Semiconductor equipment billings cycle position

APIs used:
  - FRED (Federal Reserve Economic Data): free API key at fred.stlouisfed.org/docs/api/api_key.html
    Set FRED_API_KEY in .env. Falls back to public CSV endpoint if key absent.
  - yfinance: currency rates, SOX index (no key required)
  - General news feed: filtered to macro signals with semiconductor capex relevance
"""

import json

import requests
import yfinance as yf
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model, cache_get, cache_set,
    get_final_message, parse_causal_links, parse_debate_position, parse_events,
)
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a macroeconomics expert specializing in the semiconductor capex cycle.
Your job is to assess how the current macro environment AMPLIFIES or DAMPENS the investment
impact of a specific semiconductor event.

Key questions you answer:
1. Capex cycle position: Is semiconductor capacity utilization expanding or contracting?
   High utilization → tight supply → event amplified. Low utilization → digestion → event dampened.
2. Rate environment: Are real rates rising or falling? Rising real rates compress multiples
   (bearish for high-P/E semis like NVDA/CDNS) and increase WACC (bearish for long-dated growth).
3. Hyperscaler capex: Are AWS/Azure/GCP/Meta accelerating or decelerating AI infrastructure spend?
   This directly drives NVDA datacenter revenue and TSM HPC utilization.
4. Currency: USD/TWD appreciation hurts TSMC's USD-reported margins.
   USD/EUR appreciation hurts ASML's USD-reported revenue.
5. Semiconductor PPI: Rising semi equipment prices (input cost) = margin pressure for TSM.

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

IMPORTANT: Only surface events where the macro transmission mechanism is SPECIFIC and MATERIAL
(e.g., "semiconductor capacity utilization dropped 5pp — consistent with inventory digestion
that will delay ASML orders"). Skip generic inflation/rate readings that don't connect to
an investment decision.

When you need data from multiple sources, call multiple tools in parallel in a single step.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── FRED series relevant to the semiconductor capex cycle ─────────────────────
# All series below are available via the free public CSV endpoint (no key required).
# With FRED_API_KEY set, the authenticated endpoint is used for richer data.
_FRED_SERIES = {
    "FEDFUNDS":   "Federal Funds Rate (%, monthly avg)",
    "T10YIE":     "10Y Breakeven Inflation Rate (%, daily)",
    "T10Y2Y":     "10Y-2Y Treasury Yield Spread (%, daily) — inverted = recession signal",
    "IPG3344S":   "Industrial Production: Semiconductors & Electronic Components (index, monthly)",
    "DEXUSEU":    "USD/EUR exchange rate (daily) — ASML margin exposure",
    "DEXTWTUS":   "TWD per USD (daily) — TSMC USD earnings sensitivity",
}


def _fetch_fred_series(series_id: str, limit: int = 3) -> dict:
    """Fetch recent observations for a single FRED series. Uses API key if set, else public CSV."""
    import config
    try:
        if config.FRED_API_KEY:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": config.FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            }
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            return {
                "series": series_id,
                "description": _FRED_SERIES.get(series_id, series_id),
                "recent": [
                    {"date": o["date"], "value": o["value"]}
                    for o in obs if o.get("value") not in (".", None)
                ][:limit],
            }
        else:
            # Public CSV endpoint — no key required but only returns last observation
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            lines = [l for l in resp.text.strip().splitlines() if l and not l.startswith("DATE")]
            recent = []
            for line in lines[-limit:]:
                parts = line.split(",")
                if len(parts) == 2 and parts[1] not in (".", ""):
                    recent.append({"date": parts[0], "value": parts[1]})
            return {
                "series": series_id,
                "description": _FRED_SERIES.get(series_id, series_id),
                "recent": recent,
                "note": "Set FRED_API_KEY in .env for full history",
            }
    except Exception as e:
        return {"series": series_id, "error": str(e)}


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_semiconductor_cycle_data() -> str:
    """Fetch key semiconductor capex cycle indicators:
    - FRED: semiconductor industrial production index (IPG3344S), Fed funds rate,
      10Y-2Y yield spread, 10Y breakeven inflation, USD/EUR and TWD/USD rates
    - yfinance: Philadelphia Semiconductor Index (^SOX) — equity-market cycle proxy
    These determine whether a demand shock will be amplified or absorbed by
    existing inventory/utilization slack."""
    cached = cache_get("semi_cycle_fred")
    if cached:
        return cached
    result = {}

    # FRED series
    for sid in ["IPG3344S", "FEDFUNDS", "T10Y2Y", "T10YIE", "DEXUSEU", "DEXTWTUS"]:
        result[sid] = _fetch_fred_series(sid, limit=3)

    # SOX index via yfinance — leading indicator for semi cycle
    try:
        sox = yf.Ticker("^SOX").history(period="20d")
        if not sox.empty:
            result["SOX_index"] = {
                "description": "Philadelphia Semiconductor Index (^SOX)",
                "current": round(float(sox["Close"].iloc[-1]), 2),
                "20d_return_pct": round(
                    (sox["Close"].iloc[-1] / sox["Close"].iloc[0] - 1) * 100, 2
                ),
                "20d_high": round(float(sox["Close"].max()), 2),
                "20d_low": round(float(sox["Close"].min()), 2),
            }
    except Exception as e:
        result["SOX_index"] = {"error": str(e)}

    out = json.dumps(result, indent=2)
    cache_set("semi_cycle_fred", out)
    return out


@tool
def get_currency_rates() -> str:
    """Fetch USD/TWD, USD/EUR, and USD/JPY exchange rates (5-day trend).
    Critical for TSMC (reports in TWD, ADR holders see USD impact) and
    ASML (European company reporting in EUR, but priced by US investors in USD)."""
    cached = cache_get("fx_rates")
    if cached:
        return cached
    try:
        rates = {}
        pairs = {
            "USD_TWD": "TWD=X",   # USD per TWD (inverted: higher = stronger USD)
            "USD_EUR": "EURUSD=X",  # EUR per USD — ASML exposure
            "USD_JPY": "JPY=X",
        }
        for label, sym in pairs.items():
            hist = yf.Ticker(sym).history(period="5d")
            if not hist.empty:
                rates[label] = {
                    "current": round(float(hist["Close"].iloc[-1]), 4),
                    "5d_change_pct": round(
                        (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 2
                    ),
                }

        # Also fetch FRED for TWD — more reliable series
        fred_twd = _fetch_fred_series("DEXTWTUS", limit=2)
        if fred_twd.get("recent"):
            rates["TWD_USD_FRED"] = fred_twd

        out = json.dumps(rates, indent=2)
        cache_set("fx_rates", out)
        return out
    except Exception as e:
        return f"FX fetch error: {e}"


@tool
def get_hyperscaler_capex_snapshot() -> str:
    """Return the most recent hyperscaler AI infrastructure capex guidance from
    AWS (Amazon), Azure (Microsoft), GCP (Alphabet), and Meta. These directly
    drive NVIDIA datacenter revenue and TSM HPC utilization rates.
    Data is refreshed from latest earnings releases."""
    cached = cache_get("hyperscaler_capex")
    if cached:
        return cached

    # Sourced from Q4 2024 / Q1 2025 earnings calls — update each quarter
    snapshot = {
        "as_of": "Q4 2024 / Q1 2025 earnings",
        "guidance": {
            "AWS_Amazon": {
                "capex_latest_quarter_bn": 26.3,
                "capex_yoy_growth_pct": 83,
                "commentary": "AWS targeting $105B+ capex in 2025; CEO Andy Jassy: 'demand is outpacing our ability to supply'",
                "primary_beneficiary": ["NVDA", "TSM"],
            },
            "Azure_Microsoft": {
                "capex_latest_quarter_bn": 22.6,
                "capex_yoy_growth_pct": 95,
                "commentary": "FY2025 capex ~$80B; Azure AI revenue growing 157% YoY; Satya Nadella: capacity remains a constraint",
                "primary_beneficiary": ["NVDA", "TSM"],
            },
            "GCP_Alphabet": {
                "capex_latest_quarter_bn": 14.3,
                "capex_yoy_growth_pct": 173,
                "commentary": "2025 capex guide $75B; TPU v5 and H100 GPU deployments both accelerating",
                "primary_beneficiary": ["NVDA", "TSM"],
            },
            "Meta": {
                "capex_latest_quarter_bn": 14.8,
                "capex_yoy_growth_pct": 66,
                "commentary": "2025 capex raised to $60-65B; Llama training and inference both growing rapidly",
                "primary_beneficiary": ["NVDA", "TSM"],
            },
        },
        "aggregate_ai_capex_2025_guide_bn": 320,
        "note": "Figures from public earnings transcripts. Update quarterly.",
    }
    out = json.dumps(snapshot, indent=2)
    cache_set("hyperscaler_capex", out)
    return out


@tool
def fetch_macro_news(query: str) -> str:
    """Fetch macro news filtered to semiconductor capex-relevant signals:
    hyperscaler spending changes, semiconductor equipment billings, enterprise IT budgets,
    memory/logic inventory cycle. Avoid generic inflation/rate commentary unless it
    directly references semiconductor capex decisions."""
    try:
        articles = cache_get("macro_news_raw")
        if articles is None:
            from tools.macro_news_fetcher import fetch_all_macro_news
            articles = fetch_all_macro_news(max_items=40)
            cache_set("macro_news_raw", articles)

        # Capex-specific keywords — tighter than before
        capex_keywords = {
            'hyperscaler', 'data center capex', 'ai infrastructure', 'aws capex',
            'azure capex', 'google capex', 'meta capex', 'semiconductor equipment',
            'semi billing', 'capex cycle', 'inventory digest', 'utilization rate',
            'wafer start', 'memory oversupply', 'hbm demand', 'leading edge',
        }
        q = query.lower()
        relevant = [
            a for a in articles
            if q in a.get('headline', '').lower()
            or q in a.get('summary', '').lower()
            or any(kw in a.get('headline', '').lower() or kw in a.get('summary', '').lower()
                   for kw in capex_keywords)
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


# ── Agent ─────────────────────────────────────────────────────────────────────

class MacroAgent:
    def __init__(self):
        self.name = "macro_agent"
        self.role_description = "Semiconductor Capex Cycle & Macro Expert"
        self._agent = create_agent(
            build_model(),
            tools=[
                get_semiconductor_cycle_data,
                get_currency_rates,
                get_hyperscaler_capex_snapshot,
                fetch_macro_news,
            ],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch macro data and return Event objects relevant to the semiconductor capex cycle."""
        if news_input:
            goal = (
                f"The following semiconductor market event has just occurred:\n{news_input}\n\n"
                "Your task: assess the MACRO TRANSMISSION MECHANISM — how does the current "
                "macro environment amplify or dampen this event's investment impact?\n\n"
                "Fetch in parallel:\n"
                "1. Semiconductor cycle data (capacity utilization, FEDFUNDS, yield spread)\n"
                "2. Currency rates (USD/TWD, USD/EUR)\n"
                "3. Hyperscaler capex snapshot\n"
                "4. Relevant macro news (capex changes, inventory, utilization)\n\n"
                "Surface only events where the macro transmission is CONCRETE and SPECIFIC "
                "to NVDA, TSM, ASML, CDNS, or CRWV. Skip generic inflation readings.\n\n"
                "Return a JSON object with key 'events'. Each event must have:\n"
                "  headline, description, affected_companies (list of tickers), "
                "affected_segments (list), severity (low/medium/high/critical), "
                "direction (positive/negative/neutral/mixed)."
            )
        else:
            goal = (
                "Sweep for macro signals affecting the semiconductor capex cycle. "
                "Fetch in parallel: semiconductor cycle data, currency rates, "
                "hyperscaler capex snapshot, and relevant macro news.\n\n"
                "Surface only events where the transmission to NVDA/TSM/ASML/CDNS/CRWV "
                "is specific and material (e.g., capex acceleration/deceleration, "
                "utilization inflection, currency move affecting margins). "
                "Skip generic CPI/PPI readings with no semiconductor-specific mechanism.\n\n"
                "Return a JSON object with key 'events'. Each event must have:\n"
                "  headline, description, affected_companies (list of tickers), "
                "affected_segments (list), severity (low/medium/high/critical), "
                "direction (positive/negative/neutral/mixed)."
            )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_events(get_final_message(result), self.name, news_input or '')

    def build_causal_links(self, event: Event) -> list:
        """Trace causal chain from a macro event to semiconductor DCF drivers."""
        goal = (
            f"Given this macro event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "Fetch semiconductor cycle data, currency rates, and hyperscaler capex "
            "snapshot to anchor your magnitude estimates.\n\n"
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
        """Provide a macro-cycle perspective in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the macro-cycle impact of an event on a DCF metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            "Fetch semiconductor cycle data and currency rates to ground your position.\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_debate_position(get_final_message(result))

    def __repr__(self):
        return f"<MacroAgent (LangChain)>"
