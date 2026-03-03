"""
LangGraph allocation pipeline — panel-synthesis variant.

This pipeline reuses the same domain scouts and company analysts as
`langgraph_pipeline`, but *skips* the multi-round cross-analyst debate.
Instead, the PM performs a single-shot panel synthesis over analyst briefs
and DCF valuations to allocate the fixed budget.

The original `langgraph_pipeline.graph` remains the default entry point.
Import and use this module explicitly to opt into panel-synthesis behavior.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph

import config
from agents_langchain.pm_agent import PMAgent
from langgraph_pipeline import (  # reuse detection, analysis, and finalization
    COMPANY_TICKERS,
    PipelineState,
    _initialize,
    _detect_commodities,
    _detect_macro,
    _detect_politics,
    _detect_stock_market,
    _detect_tech_publications,
    _merge_and_route_events,
    _analyze_nvda,
    _analyze_cdns,
    _analyze_crwv,
    _analyze_tsm,
    _analyze_asml,
    _normalise_allocations,
    _finalize,
)
from tools import slack_notifier


def _pm_panel_and_allocate(state: PipelineState) -> PipelineState:
    """
    PM-led single-shot panel synthesis and allocation (no multi-round debate).

    Uses the same company analyst briefs and DCF grounding as the original
    pipeline, but treats the analyst set as a panel and allocates capital
    in one step based on:
      - short_term_event_conviction
      - long-term conviction
      - DCF upside as a secondary risk filter
    """
    budget = float(state.get("budget") or 1000.0)
    briefs = state.get("company_briefs_raw", [])
    merged_events = state.get("merged_events", [])

    if not briefs:
        return {"error": "No company briefs generated.", "allocation_dollars": {}}

    print("  [PM-panel] Synthesizing analyst panel and allocating $%.0f..." % budget)

    # ── DCF valuations from analyst-proposed deltas ───────────────────────────
    from dcf_grounding import compute_baseline, apply_deltas_and_compute

    dcf_results: dict[str, dict] = {}
    for brief in briefs:
        ticker = brief.get("ticker", "")
        deltas = brief.get("proposed_driver_deltas", {})

        if deltas:
            dcf_result = apply_deltas_and_compute(ticker, deltas)
        else:
            baseline = compute_baseline(ticker)
            dcf_result = (
                {
                    "baseline_price": baseline["implied_price"],
                    "adjusted_price": baseline["implied_price"],
                    "current_price": baseline["current_price"],
                    "upside": baseline["upside"],
                    "alpha_vs_baseline": 0.0,
                }
                if baseline
                else None
            )

        if dcf_result:
            dcf_results[ticker] = dcf_result
            print(
                "  [PM-panel] DCF %s: baseline=$%.2f, adjusted=$%.2f, upside=%.1f%%, alpha=$%.2f"
                % (
                    ticker,
                    dcf_result.get("baseline_price", 0),
                    dcf_result.get("adjusted_price", 0),
                    dcf_result.get("upside", 0) * 100,
                    dcf_result.get("alpha_vs_baseline", 0),
                )
            )

    dcf_summary_lines = []
    for ticker, dr in dcf_results.items():
        dcf_summary_lines.append(
            f"  {ticker}: baseline=${dr.get('baseline_price',0):.2f}, "
            f"analyst-adjusted=${dr.get('adjusted_price',0):.2f}, "
            f"market=${dr.get('current_price',0):.2f}, "
            f"upside={dr.get('upside',0):+.1%}, "
            f"alpha_vs_baseline=${dr.get('alpha_vs_baseline',0):+.2f}"
        )
    dcf_block = (
        "\n".join(dcf_summary_lines) if dcf_summary_lines else "(no DCF models available)"
    )

    if dcf_summary_lines:
        slack_notifier.post(
            "*DCF Valuations (analyst-adjusted, panel variant):*\n```\n"
            + "\n".join(
                f"{t}: adj=${dr.get('adjusted_price', 0):.2f}  "
                f"mkt=${dr.get('current_price', 0):.2f}  "
                f"upside={dr.get('upside', 0):+.1%}"
                for t, dr in dcf_results.items()
            )
            + "\n```"
        )

    pm = PMAgent()

    panel_goal = (
        "You are the Portfolio Manager (PM) synthesizing a panel of company analysts "
        "into a single, event-driven allocation decision.\n\n"
        f"FIXED_BUDGET_DOLLARS: {budget}\n"
        f"COVERED_COMPANIES: {', '.join(COMPANY_TICKERS)}\n\n"
        f"RECENT_DOMAIN_EVENTS:\n{json.dumps(merged_events[:15], indent=2, default=str)}\n\n"
        f"COMPANY_ANALYST_BRIEFS:\n{json.dumps(briefs, indent=2, default=str)}\n\n"
        f"DCF VALUATIONS (analyst-adjusted):\n{dcf_block}\n\n"
        "Task:\n"
        "1) Treat each analyst brief as one vote in a panel.\n"
        "2) Weight allocation primarily by short_term_event_conviction × conviction.\n"
        "3) Favor CONCENTRATION in the top 1–2 names with the strongest event-driven signal; "
        "use DCF upside only as a secondary risk filter (e.g., trim modestly if upside is deeply negative), "
        "but never allocate negative dollars.\n"
        "4) Allocate the FULL fixed budget across companies.\n\n"
        "Return ONLY JSON with keys:\n"
        "  debate_summary (string),\n"
        "  rationale (string referencing event conviction and DCF risk-filter applied),\n"
        "  risk_notes (list of strings),\n"
        "  event_conviction_rankings (list of {ticker, short_term_event_conviction, conviction, rationale}),\n"
        "  allocation_dollars (dict ticker->float) including all covered companies."
    )

    try:
        panel_result = pm._pm_invoke(panel_goal)
        raw_alloc: dict[str, Any] = panel_result.get("allocation_dollars", {}) or {}
        alloc_dollars = _normalise_allocations(raw_alloc, budget)
        alloc_pct = (
            {t: round(v / budget, 4) for t, v in alloc_dollars.items()}
            if budget > 0
            else {t: 0.0 for t in COMPANY_TICKERS}
        )

        # Align with existing finalize() expectations
        panel_result["dcf_valuations"] = dcf_results
        panel_result["debate_rounds_run"] = 0
        panel_result["challenge_transcript"] = []
        panel_result["pre_debate_briefs"] = briefs
        panel_result["debate_gated"] = False

        summary = (panel_result.get("debate_summary") or "")[:120]
        print(
            "  [PM-panel] → allocation done. Panel summary: %s"
            % (
                summary + "..."
                if len(panel_result.get("debate_summary") or "") > 120
                else summary
            )
        )

        # Post PM panel summary
        slack_notifier.post(
            f"*PM Panel Summary (no multi-round debate):*\n_"
            f"{(panel_result.get('debate_summary') or '')[:400]}_\n\n"
            f"*Rationale:* {(panel_result.get('rationale') or '')[:300]}"
        )

        # Post final allocation
        alloc_lines = "\n".join(
            f"  {t}: ${v:.0f} ({v / budget:.0%})" for t, v in alloc_dollars.items()
        )
        slack_notifier.post(
            f"*Final Allocation — Panel Variant (budget=${budget:.0f}):*\n```\n{alloc_lines}\n```"
        )

        return {
            "debate": panel_result,
            "allocation_dollars": alloc_dollars,
            "allocation_pct": alloc_pct,
            "error": None,
        }
    except Exception as exc:
        print("  [PM-panel] → ERROR: %s" % exc)
        return {"error": f"PM panel/allocation failed: {exc}", "allocation_dollars": {}}


def build_graph_panel():
    """Build and compile PM-led panel-synthesis allocation graph."""
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

    # PM panel synthesis + finalization
    graph.add_node("pm_panel_and_allocate", _pm_panel_and_allocate)
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

    # Fan in to PM panel and finalize
    graph.add_edge("analyze_nvda", "pm_panel_and_allocate")
    graph.add_edge("analyze_cdns", "pm_panel_and_allocate")
    graph.add_edge("analyze_crwv", "pm_panel_and_allocate")
    graph.add_edge("analyze_tsm", "pm_panel_and_allocate")
    graph.add_edge("analyze_asml", "pm_panel_and_allocate")

    graph.add_edge("pm_panel_and_allocate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


graph_panel = build_graph_panel()

