"""
LangGraph allocation pipeline with PM-led multi-agent coordination.

Flow:
1) PM kicks off domain scouts in parallel (commodities, macro, politics,
   stock market, tech publications), constrained to last-hour changes.
2) PM routes detected changes to affected company analysts.
3) Company analysts produce company briefs and allocation stances.
4) PM facilitates debate and returns a fixed-budget allocation.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import config
from agents_langchain.base import clear_session_cache, extract_json, get_final_message
from agents_langchain.commodities_agent import CommoditiesAgent
from agents_langchain.company_analyst_agent import CompanyAnalystAgent
from agents_langchain.macro_agent import MacroAgent
from agents_langchain.pm_agent import PMAgent
from agents_langchain.politics_agent import PoliticsAgent
from agents_langchain.stock_market_agent import StockMarketAgent
from agents_langchain.tech_publications_agent import TechPublicationsAgent
from models.event import Event


COMPANY_TICKERS = list(config.COMPANIES.keys())
DOMAIN_AGENT_NAMES = (
    "commodities_agent",
    "macro_agent",
    "politics_agent",
    "stock_market_agent",
    "tech_publications_agent",
)


class PipelineState(TypedDict, total=False):
    # Inputs
    event: str
    lookback_hours: int
    budget: float
    # Detection phase (parallel fan-out reducers)
    domain_outputs: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    # Routed company context
    merged_events: list[dict[str, Any]]
    company_event_map: dict[str, list[dict[str, Any]]]
    # Company analysis phase (parallel fan-out reducers)
    company_briefs_raw: Annotated[list[dict[str, Any]], operator.add]
    # PM output
    debate: dict[str, Any]
    allocation_dollars: dict[str, float]
    allocation_pct: dict[str, float]
    result: Optional[dict[str, Any]]
    error: Optional[str]


def _initialize(state: PipelineState) -> PipelineState:
    clear_session_cache()
    event = (state.get("event") or "").strip()
    if not event:
        event = (
            "Run autonomous last-hour change detection across macro, geopolitics, "
            "commodities, market structure, and semiconductor technology updates."
        )
    lookback = int(state.get("lookback_hours") or 1)
    budget = float(state.get("budget") or 1000.0)
    print("\n  [PM] Initializing pipeline: lookback=%sh, budget=$%.0f" % (lookback, budget))
    print("  [PM] Kicking off domain scouts in parallel (commodities, macro, politics, stock_market, tech_publications).\n")
    return {
        "event": event,
        "lookback_hours": lookback,
        "budget": budget,
    }


def _safe_event_to_dict(event: Any) -> Optional[dict[str, Any]]:
    if isinstance(event, Event):
        return event.to_dict()
    if isinstance(event, dict):
        return event
    return None


def _domain_prompt_context(state: PipelineState) -> str:
    lookback = int(state.get("lookback_hours") or 1)
    user_context = (state.get("event") or "").strip()
    base = (
        f"Focus only on relevant changes from the last {lookback} hour(s). "
        f"For every change, explicitly tag affected companies from: {', '.join(COMPANY_TICKERS)}."
    )
    if user_context:
        return f"{base}\n\nAdditional context from PM:\n{user_context}"
    return base


def _run_domain_detector(agent: Any, agent_name: str, state: PipelineState) -> PipelineState:
    lookback = int(state.get("lookback_hours") or 1)
    print("  [%s] Scanning last %s hour(s) for relevant changes..." % (agent_name, lookback))
    try:
        events = agent.detect_events(_domain_prompt_context(state)) or []
        serialised = [e for e in (_safe_event_to_dict(ev) for ev in events) if e]
        headlines = [e.get("headline", "")[:60] for e in serialised[:5]]
        if serialised:
            print("  [%s] → %d event(s): %s" % (agent_name, len(serialised), "; ".join(headlines) or "(no headline)"))
        else:
            print("  [%s] → 0 events (no material changes in window)" % agent_name)
        return {"domain_outputs": [{"agent": agent_name, "events": serialised}]}
    except Exception as exc:
        print("  [%s] → ERROR: %s" % (agent_name, exc))
        return {
            "domain_outputs": [{"agent": agent_name, "events": []}],
            "errors": [f"{agent_name} failed: {exc}"],
        }


def _detect_commodities(state: PipelineState) -> PipelineState:
    return _run_domain_detector(CommoditiesAgent(), "commodities_agent", state)


def _detect_macro(state: PipelineState) -> PipelineState:
    return _run_domain_detector(MacroAgent(), "macro_agent", state)


def _detect_politics(state: PipelineState) -> PipelineState:
    return _run_domain_detector(PoliticsAgent(), "politics_agent", state)


def _detect_stock_market(state: PipelineState) -> PipelineState:
    return _run_domain_detector(StockMarketAgent(), "stock_market_agent", state)


def _detect_tech_publications(state: PipelineState) -> PipelineState:
    return _run_domain_detector(TechPublicationsAgent(), "tech_publications_agent", state)


def _merge_and_route_events(state: PipelineState) -> PipelineState:
    seen: set[tuple[str, str]] = set()
    merged_events: list[dict[str, Any]] = []
    company_event_map = {ticker: [] for ticker in COMPANY_TICKERS}

    print("  [merge] Deduplicating and routing events to company analysts...")
    for domain_output in state.get("domain_outputs", []):
        agent_name = domain_output.get("agent", "unknown_agent")
        for evt in domain_output.get("events", []):
            evt_dict = dict(evt)
            evt_dict["source_agent"] = evt_dict.get("source_agent", agent_name)
            headline = (evt_dict.get("headline") or "").strip().lower()
            key = (agent_name, headline)
            if not headline or key in seen:
                continue
            seen.add(key)
            merged_events.append(evt_dict)

            affected = [
                t for t in evt_dict.get("affected_companies", [])
                if t in COMPANY_TICKERS
            ]
            for ticker in affected:
                company_event_map[ticker].append(evt_dict)

    routed = " | ".join("%s: %d" % (t, len(company_event_map[t])) for t in COMPANY_TICKERS)
    print("  [merge] → %d unique events; routed by company: %s" % (len(merged_events), routed))
    return {"merged_events": merged_events, "company_event_map": company_event_map}


def _analyze_company(ticker: str, state: PipelineState) -> PipelineState:
    budget = float(state.get("budget") or 1000.0)
    company_events = state.get("company_event_map", {}).get(ticker, [])
    print("  [analyst_%s] Analyzing %d routed event(s); forming thesis and allocation stance..." % (ticker, len(company_events)))
    analyst = CompanyAnalystAgent(ticker)

    events_block = json.dumps(company_events[:8], indent=2, default=str)
    goal = (
        f"You are the fundamental analyst for {ticker}.\n\n"
        "Review the recent routed events (last-hour domain changes), then produce "
        "a concise investment stance for this company.\n\n"
        f"ROUTED_EVENTS:\n{events_block}\n\n"
        "Return ONLY JSON with keys:\n"
        "  ticker,\n"
        "  thesis (2-4 sentences),\n"
        "  key_drivers (list of strings),\n"
        "  key_risks (list of strings),\n"
        "  conviction (0.0-1.0),\n"
        f"  recommended_dollars (0-{budget}),\n"
        "  recommended_weight (0.0-1.0),\n"
        "  challenge_to_others (1-2 sentences).\n"
    )

    try:
        result = analyst._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        brief = extract_json(get_final_message(result))
        brief["ticker"] = ticker
        conv = brief.get("conviction", 0)
        rec_d = brief.get("recommended_dollars", 0)
        thesis_preview = (brief.get("thesis") or "")[:80]
        print("  [analyst_%s] → conviction=%.2f, recommended=$%.0f | %s" % (ticker, conv, rec_d, thesis_preview + ("..." if len(brief.get("thesis") or "") > 80 else "")))
        return {"company_briefs_raw": [brief]}
    except Exception as exc:
        print("  [analyst_%s] → ERROR: %s" % (ticker, exc))
        return {
            "company_briefs_raw": [{
                "ticker": ticker,
                "thesis": f"Analyst error for {ticker}",
                "key_drivers": [],
                "key_risks": [str(exc)],
                "conviction": 0.0,
                "recommended_dollars": 0.0,
                "recommended_weight": 0.0,
                "challenge_to_others": "",
            }],
            "errors": [f"analyst_{ticker.lower()} failed: {exc}"],
        }


def _analyze_nvda(state: PipelineState) -> PipelineState:
    return _analyze_company("NVDA", state)


def _analyze_cdns(state: PipelineState) -> PipelineState:
    return _analyze_company("CDNS", state)


def _analyze_crwv(state: PipelineState) -> PipelineState:
    return _analyze_company("CRWV", state)


def _analyze_tsm(state: PipelineState) -> PipelineState:
    return _analyze_company("TSM", state)


def _analyze_asml(state: PipelineState) -> PipelineState:
    return _analyze_company("ASML", state)


def _normalise_allocations(raw_alloc: dict[str, Any], budget: float) -> dict[str, float]:
    alloc = {ticker: float(raw_alloc.get(ticker, 0.0) or 0.0) for ticker in COMPANY_TICKERS}
    total = sum(alloc.values())
    if total <= 0:
        equal = round(budget / len(COMPANY_TICKERS), 2)
        fallback = {t: equal for t in COMPANY_TICKERS}
        # rounding guard for exact budget match
        diff = round(budget - sum(fallback.values()), 2)
        fallback[COMPANY_TICKERS[0]] = round(fallback[COMPANY_TICKERS[0]] + diff, 2)
        return fallback

    scaled = {t: round(v * budget / total, 2) for t, v in alloc.items()}
    diff = round(budget - sum(scaled.values()), 2)
    largest = max(scaled, key=scaled.get)
    scaled[largest] = round(scaled[largest] + diff, 2)
    return scaled


def _pm_debate_and_allocate(state: PipelineState) -> PipelineState:
    budget = float(state.get("budget") or 1000.0)
    briefs = state.get("company_briefs_raw", [])
    merged_events = state.get("merged_events", [])

    if not briefs:
        return {"error": "No company briefs generated.", "allocation_dollars": {}}

    print("  [PM] Facilitating cross-company debate and allocating $%.0f..." % budget)
    pm = PMAgent()
    debate_goal = (
        "You are the PM facilitating a cross-company analyst debate and final capital allocation.\n\n"
        f"FIXED_BUDGET_DOLLARS: {budget}\n"
        f"COVERED_COMPANIES: {', '.join(COMPANY_TICKERS)}\n\n"
        f"RECENT_DOMAIN_EVENTS:\n{json.dumps(merged_events[:15], indent=2, default=str)}\n\n"
        f"COMPANY_ANALYST_BRIEFS:\n{json.dumps(briefs, indent=2, default=str)}\n\n"
        "Task:\n"
        "1) Summarize key agreements/disagreements across analysts.\n"
        "2) Challenge weak claims and identify highest-conviction opportunities.\n"
        "3) Allocate the FULL fixed budget across companies.\n\n"
        "Return ONLY JSON with keys:\n"
        "  debate_summary (string),\n"
        "  rationale (string),\n"
        "  risk_notes (list of strings),\n"
        "  allocation_dollars (dict ticker->float) including all covered companies."
    )

    try:
        debate_result = pm._pm_invoke(debate_goal)
        raw_alloc = debate_result.get("allocation_dollars", {})
        alloc_dollars = _normalise_allocations(raw_alloc, budget)
        alloc_pct = {t: round(v / budget, 4) for t, v in alloc_dollars.items()} if budget > 0 else {
            t: 0.0 for t in COMPANY_TICKERS
        }
        summary = (debate_result.get("debate_summary") or "")[:120]
        print("  [PM] → allocation done. Debate summary: %s" % (summary + "..." if len(debate_result.get("debate_summary") or "") > 120 else summary))
        return {
            "debate": debate_result,
            "allocation_dollars": alloc_dollars,
            "allocation_pct": alloc_pct,
            "error": None,
        }
    except Exception as exc:
        print("  [PM] → ERROR: %s" % exc)
        return {"error": f"PM debate/allocation failed: {exc}", "allocation_dollars": {}}


def _finalize(state: PipelineState) -> PipelineState:
    budget = float(state.get("budget") or 1000.0)
    allocation = state.get("allocation_dollars", {})
    print("  [finalize] Pipeline complete. Total allocated: $%.2f" % sum(allocation.values()))
    result = {
        "budget": budget,
        "lookback_hours": int(state.get("lookback_hours") or 1),
        "domain_agents": list(DOMAIN_AGENT_NAMES),
        "events_detected": len(state.get("merged_events", [])),
        "routed_events_by_company": {
            t: len(v) for t, v in state.get("company_event_map", {}).items()
        },
        "allocation_dollars": allocation,
        "allocation_pct": state.get("allocation_pct", {}),
        "debate_summary": state.get("debate", {}).get("debate_summary", ""),
        "rationale": state.get("debate", {}).get("rationale", ""),
        "risk_notes": state.get("debate", {}).get("risk_notes", []),
        "errors": state.get("errors", []),
    }
    return {"result": result, "error": state.get("error")}


def build_graph():
    """Build and compile PM-led portfolio-allocation graph for LangSmith Cloud."""
    graph = StateGraph(PipelineState)

    graph.add_node("initialize", _initialize)

    # Parallel domain detection
    graph.add_node("detect_commodities", _detect_commodities)
    graph.add_node("detect_macro", _detect_macro)
    graph.add_node("detect_politics", _detect_politics)
    graph.add_node("detect_stock_market", _detect_stock_market)
    graph.add_node("detect_tech_publications", _detect_tech_publications)
    graph.add_node("merge_and_route_events", _merge_and_route_events)

    # Parallel company analysis
    graph.add_node("analyze_nvda", _analyze_nvda)
    graph.add_node("analyze_cdns", _analyze_cdns)
    graph.add_node("analyze_crwv", _analyze_crwv)
    graph.add_node("analyze_tsm", _analyze_tsm)
    graph.add_node("analyze_asml", _analyze_asml)

    # PM finalization
    graph.add_node("pm_debate_and_allocate", _pm_debate_and_allocate)
    graph.add_node("finalize", _finalize)

    # Fan out to domain scouts
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "detect_commodities")
    graph.add_edge("initialize", "detect_macro")
    graph.add_edge("initialize", "detect_politics")
    graph.add_edge("initialize", "detect_stock_market")
    graph.add_edge("initialize", "detect_tech_publications")

    # Fan in to merge node
    graph.add_edge("detect_commodities", "merge_and_route_events")
    graph.add_edge("detect_macro", "merge_and_route_events")
    graph.add_edge("detect_politics", "merge_and_route_events")
    graph.add_edge("detect_stock_market", "merge_and_route_events")
    graph.add_edge("detect_tech_publications", "merge_and_route_events")

    # Fan out to company analysts
    graph.add_edge("merge_and_route_events", "analyze_nvda")
    graph.add_edge("merge_and_route_events", "analyze_cdns")
    graph.add_edge("merge_and_route_events", "analyze_crwv")
    graph.add_edge("merge_and_route_events", "analyze_tsm")
    graph.add_edge("merge_and_route_events", "analyze_asml")

    # Fan in to PM
    graph.add_edge("analyze_nvda", "pm_debate_and_allocate")
    graph.add_edge("analyze_cdns", "pm_debate_and_allocate")
    graph.add_edge("analyze_crwv", "pm_debate_and_allocate")
    graph.add_edge("analyze_tsm", "pm_debate_and_allocate")
    graph.add_edge("analyze_asml", "pm_debate_and_allocate")

    graph.add_edge("pm_debate_and_allocate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


graph = build_graph()
