"""
LangGraph pipeline for Council of Agents — deployable to LangSmith Cloud.

Exposes the 4-phase pipeline (detect → causal → debate → DCF) as a single
LangGraph so it can be deployed and triggered on a schedule (e.g. cron every hour).

State:
  - event: str — event description or news context (empty = autonomous news detection)
  - company: str — target company ticker (default NVDA)
  - result: dict | None — pipeline output (valuation, etc.)
  - error: str | None — error message if the pipeline failed
"""

from typing import TypedDict, Optional

from langgraph.graph import StateGraph, START, END


class PipelineState(TypedDict, total=False):
    """State for the council pipeline graph."""
    event: str
    company: str
    result: Optional[dict]
    error: Optional[str]


def _run_pipeline_node(state: PipelineState) -> PipelineState:
    """Run the full 4-phase pipeline (detect → causal → debate → DCF)."""
    event = (state.get("event") or "").strip()
    company = (state.get("company") or "NVDA").strip().upper() or "NVDA"

    # Default for scheduled/cron: agents fetch latest news autonomously
    if not event:
        event = (
            "Run scheduled pipeline: detect latest semiconductor and macro news "
            "using agent tools, then run causal graph, debate, and DCF valuation."
        )

    try:
        from agents_langchain.pm_agent import PMAgent
        pm = PMAgent()
        result = pm.run_full_pipeline(event, target_company=company)
        return {"result": result or {}, "error": None}
    except Exception as e:
        return {"result": None, "error": str(e)}


def build_graph():
    """Build and compile the pipeline graph. Used by langgraph.json."""
    graph = StateGraph(PipelineState)
    graph.add_node("run_pipeline", _run_pipeline_node)
    graph.add_edge(START, "run_pipeline")
    graph.add_edge("run_pipeline", END)
    return graph.compile()


# Compiled graph instance for LangGraph CLI / LangSmith Cloud
graph = build_graph()
