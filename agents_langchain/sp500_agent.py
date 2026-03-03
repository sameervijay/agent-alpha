"""
S&P 500 Benchmark Agent — LangChain version.

Provides a benchmark view on the S&P 500 (via SPY) so the PM
can explicitly compare single‑stock ideas against the index
and optionally allocate part of the portfolio to the benchmark.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import yfinance as yf
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model,
    cache_get,
    cache_set,
    extract_json,
    get_final_message,
)


BENCHMARK_TICKER = "SPY"  # S&P 500 proxy


SYSTEM_PROMPT = """You are the S&P 500 benchmark portfolio strategist.

Your job is to:
- Maintain a live view on the S&P 500 (proxied via SPY)
- Summarize its near-term risk/reward given the current macro / event context
- Provide a clear baseline that single-stock analysts must BEAT on a risk-adjusted basis

Always think in terms of:
- Near-term expected return vs downside over the next 2–4 weeks
- How concentrated semiconductor bets compare to diversified S&P 500 exposure
- When it is prudent to keep more capital in the benchmark vs active stock picks

Always return your final answer as a single JSON object — no prose outside JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────


@tool
def get_sp500_snapshot(lookback_days: int = 60) -> str:
    """Get recent SPY price performance and volatility over a lookback window."""
    key = f"sp500_snapshot:{lookback_days}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        end = datetime.utcnow()
        start = end - timedelta(days=max(lookback_days, 10))
        hist = yf.Ticker(BENCHMARK_TICKER).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )
        if hist.empty:
            out = json.dumps(
                {
                    "ticker": BENCHMARK_TICKER,
                    "error": "No SPY history available for requested window.",
                }
            )
            cache_set(key, out)
            return out

        prices = hist["Close"]
        p0 = float(prices.iloc[0])
        p_last = float(prices.iloc[-1])
        ret_pct = (p_last / p0 - 1.0) * 100.0 if p0 > 0 else 0.0
        daily_rets = prices.pct_change().dropna()
        vol_annual = float(daily_rets.std() * (252 ** 0.5)) * 100.0 if not daily_rets.empty else 0.0

        snapshot = {
            "ticker": BENCHMARK_TICKER,
            "start_date": prices.index[0].strftime("%Y-%m-%d"),
            "end_date": prices.index[-1].strftime("%Y-%m-%d"),
            "price_start": round(p0, 2),
            "price_last": round(p_last, 2),
            "return_pct": round(ret_pct, 2),
            "annual_vol_pct": round(vol_annual, 2),
            "num_points": len(prices),
        }
        out = json.dumps(snapshot, indent=2, default=str)
        cache_set(key, out)
        return out
    except Exception as exc:
        return json.dumps(
            {
                "ticker": BENCHMARK_TICKER,
                "error": f"SPY snapshot error: {exc}",
            }
        )


# ── Agent ─────────────────────────────────────────────────────────────────────


class SP500Agent:
    """Benchmark agent that produces an S&P 500 (SPY) view for the PM."""

    def __init__(self):
        self.ticker = BENCHMARK_TICKER
        self.name = "sp500_agent"
        self.role_description = "S&P 500 benchmark strategist"
        self._agent = create_agent(
            build_model(),
            tools=[get_sp500_snapshot],
            system_prompt=SYSTEM_PROMPT,
        )

    def build_benchmark_brief(self, event_context: str | None, budget: float) -> dict:
        """
        Produce a concise benchmark brief for the S&P 500.

        Returns JSON with keys:
          ticker,
          thesis,
          benchmark_role,
          near_term_view,
          risk_notes (list of strings),
          conviction (0.0-1.0),
          short_term_event_conviction (0.0-1.0),
          recommended_dollars (0-budget),
          recommended_weight (0.0-1.0).
        """
        ctx = (event_context or "").strip()
        goal = (
            f"You are the benchmark strategist for the S&P 500 (proxied via {BENCHMARK_TICKER}).\n\n"
            "First, call get_sp500_snapshot to understand recent return and volatility.\n\n"
            "Then, given the current event context (if any), explain how attractive the S&P 500 "
            "is as a near-term (2–4 week) holding versus concentrated semiconductor stock bets.\n\n"
            f"EVENT_CONTEXT:\n{ctx or '(no explicit event provided — use your best judgment)'}\n\n"
            f"Budget for the overall portfolio (stocks + benchmark) is ${budget:,.0f}.\n\n"
            "Return ONLY JSON with keys:\n"
            "  ticker (must be 'SPY'),\n"
            "  thesis (2–4 sentences on S&P 500 risk/reward in this environment),\n"
            "  benchmark_role (1–2 sentences on when capital should stay in the index vs active stock picks),\n"
            "  near_term_view (1–2 sentences summarizing expected 2–4 week performance),\n"
            "  risk_notes (list of 2–4 specific risks to the index),\n"
            "  conviction (0.0-1.0 — confidence in the S&P 500 as a baseline holding over the next 2–4 weeks),\n"
            "  short_term_event_conviction (0.0-1.0 — how much this specific event should move index exposure up/down),\n"
            f"  recommended_dollars (0-{budget:.0f} — how many dollars to keep in S&P 500 exposure),\n"
            "  recommended_weight (0.0-1.0 — share of total budget that should be in S&P 500).\n"
            "Make sure recommended_dollars and recommended_weight are internally consistent."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        brief = extract_json(get_final_message(result))
        brief.setdefault("ticker", BENCHMARK_TICKER)
        return brief

    def __repr__(self) -> str:
        return "<SP500Agent (LangChain)>"

