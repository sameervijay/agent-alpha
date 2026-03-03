"""
Debate Ablation Experiment
===========================
Runs the LangGraph pipeline under 3 conditions and compares allocations:

  A) no_analysts   — PM sees only events + DCF/multiples valuations (no analyst input)
  B) analysts_only — PM sees analyst briefs but NO cross-analyst debate (debate_rounds=0)
  C) full_debate   — Current system with cross-analyst challenges + PM probing

Usage:
    python eval/debate_ablation.py                                    # live events, 1 debate round
    python eval/debate_ablation.py --event "TSMC raises capex"        # custom event
    python eval/debate_ablation.py --rounds 2                         # 2 debate rounds
    python eval/debate_ablation.py --backtest                         # run on HISTORICAL_EVENTS
    python eval/debate_ablation.py --backtest --rounds 2              # backtest with 2 rounds
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

COMPANY_TICKERS = list(config.COMPANIES.keys())

# Mapping from condition name → portfolio profile name
CONDITION_PROFILES = {
    "no_analysts":   "pm_noanalysts",
    "analysts_only": "pm_nodebate",
    "full_debate":   "pm",
}

CONDITIONS = [
    {"name": "no_analysts",   "no_analysts": True,  "debate_rounds": 0},
    {"name": "analysts_only", "no_analysts": False, "debate_rounds": 0},
    {"name": "full_debate",   "no_analysts": False, "debate_rounds": None},  # filled from args
]


def run_single_experiment(
    event: str,
    budget: float,
    lookback_hours: int,
    condition: dict,
) -> dict:
    """Run the pipeline once under a given condition. Returns result dict."""
    from langgraph_pipeline import build_graph

    graph = build_graph()
    state = {
        "event": event,
        "lookback_hours": lookback_hours,
        "budget": budget,
        "no_analysts": condition["no_analysts"],
        "debate_rounds": condition["debate_rounds"],
    }

    t0 = time.time()
    out = graph.invoke(state)
    elapsed = time.time() - t0

    result = out.get("result", {})
    if result is None:
        result = {}
    result["condition"] = condition["name"]
    result["elapsed_s"] = round(elapsed, 1)
    result["error"] = out.get("error")
    return result


def compute_hhi(allocation: dict[str, float]) -> float:
    """Herfindahl-Hirschman Index — concentration measure.

    HHI = sum(weight_i^2). Range: 1/N (equal) to 1.0 (all in one).
    """
    total = sum(allocation.values())
    if total <= 0:
        return 0.0
    weights = [v / total for v in allocation.values() if v > 0]
    return round(sum(w ** 2 for w in weights), 4)


def compute_conviction_shift(benchmark: dict) -> float:
    """Mean absolute allocation shift from pre-debate to post-debate."""
    pre = benchmark.get("pre_debate_allocation", {})
    post = benchmark.get("post_debate_allocation", {})
    tickers = set(pre) | set(post)
    if not tickers:
        return 0.0
    shifts = [abs(post.get(t, 0) - pre.get(t, 0)) for t in tickers]
    return round(sum(shifts) / len(shifts), 2)


def run_ablation(
    event: str,
    budget: float = 1000.0,
    lookback_hours: int = 1,
    debate_rounds: int = 1,
    init_portfolios: bool = False,
) -> list[dict]:
    """Run all 3 conditions and return list of results.

    If init_portfolios=True, initializes (or rebalances) a separate portfolio
    profile for each condition based on its allocation.
    """
    results = []

    for cond in CONDITIONS:
        cond = dict(cond)  # copy
        if cond["debate_rounds"] is None:
            cond["debate_rounds"] = debate_rounds

        print(f"\n{'=' * 70}")
        print(f"  CONDITION: {cond['name']} (no_analysts={cond['no_analysts']}, "
              f"debate_rounds={cond['debate_rounds']})")
        print(f"{'=' * 70}")

        result = run_single_experiment(event, budget, lookback_hours, cond)

        # Compute extra metrics from benchmark data
        benchmark = result.get("benchmark", {})
        alloc = result.get("allocation_dollars", {})
        result["hhi"] = compute_hhi(alloc)
        result["allocation_shift"] = compute_conviction_shift(benchmark)

        # Portfolio init/rebalance for this condition
        if init_portfolios and alloc:
            profile = CONDITION_PROFILES.get(cond["name"])
            if profile:
                _sync_portfolio(profile, alloc)

        results.append(result)

    return results


def _sync_portfolio(profile: str, allocation_dollars: dict[str, float]) -> None:
    """Initialize or rebalance a portfolio profile from an allocation dict."""
    from eval.pm_portfolio import init_portfolio, rebalance, _trades_path

    print(f"\n  --- Portfolio sync for profile '{profile}' ---")
    if _trades_path(profile).exists():
        print(f"  Portfolio '{profile}' exists — rebalancing.")
        rebalance(allocation_dollars, profile=profile)
    else:
        print(f"  Portfolio '{profile}' does not exist — initializing.")
        init_portfolio(allocation_dollars, profile=profile)


def print_comparison(results: list[dict]):
    """Print a formatted comparison table."""
    print(f"\n{'=' * 90}")
    print(f"  DEBATE ABLATION — COMPARISON")
    print(f"{'=' * 90}")

    names = [r.get("condition", "?") for r in results]
    print(f"  {'Metric':<30} " + "".join(f"{n:>20}" for n in names))
    print(f"  {'-' * (30 + 20 * len(names))}")

    # Allocation per ticker
    for t in COMPANY_TICKERS:
        vals = []
        for r in results:
            alloc = r.get("allocation_dollars", {})
            vals.append(f"${alloc.get(t, 0):>8.0f}")
        print(f"  {t + ' allocation':<30} " + "".join(f"{v:>20}" for v in vals))

    print(f"  {'-' * (30 + 20 * len(names))}")

    # Benchmark scores
    for label, key in [("Pre-debate score", "pre_score"), ("Post-debate score", "post_score"),
                        ("Score delta", "score_delta")]:
        vals = []
        for r in results:
            bm = r.get("benchmark", {})
            vals.append(f"{bm.get(key, 0):>8.4f}")
        print(f"  {label:<30} " + "".join(f"{v:>20}" for v in vals))

    # HHI
    vals = [f"{r.get('hhi', 0):>8.4f}" for r in results]
    print(f"  {'HHI (concentration)':<30} " + "".join(f"{v:>20}" for v in vals))

    # Allocation shift
    vals = [f"${r.get('allocation_shift', 0):>7.0f}" for r in results]
    print(f"  {'Avg allocation shift':<30} " + "".join(f"{v:>20}" for v in vals))

    # Debate info
    for label, key in [("Debate gated?", "debate_gated"), ("Analyst disagreement", "analyst_disagreement_mad")]:
        vals = []
        for r in results:
            bm = r.get("benchmark", {})
            v = bm.get(key, "N/A")
            if isinstance(v, float):
                vals.append(f"{v:>8.4f}")
            else:
                vals.append(f"{v!s:>8}")
        print(f"  {label:<30} " + "".join(f"{v:>20}" for v in vals))

    # Elapsed time
    vals = [f"{r.get('elapsed_s', 0):>7.1f}s" for r in results]
    print(f"  {'Elapsed time':<30} " + "".join(f"{v:>20}" for v in vals))

    # Errors
    for r in results:
        if r.get("error"):
            print(f"\n  WARNING [{r['condition']}]: {r['error']}")

    print(f"{'=' * 90}\n")


def run_backtest_ablation(
    budget: float = 1000.0,
    debate_rounds: int = 1,
) -> list[dict]:
    """Run ablation on all HISTORICAL_EVENTS from backtest.py."""
    from eval.backtest import HISTORICAL_EVENTS

    all_results = []
    for i, hist_event in enumerate(HISTORICAL_EVENTS):
        print(f"\n{'#' * 70}")
        print(f"  BACKTEST EVENT {i+1}/{len(HISTORICAL_EVENTS)}: {hist_event['id']} ({hist_event['date']})")
        print(f"{'#' * 70}")

        results = run_ablation(
            event=hist_event["news_input"],
            budget=budget,
            debate_rounds=debate_rounds,
        )

        for r in results:
            r["backtest_event_id"] = hist_event["id"]
            r["backtest_date"] = hist_event["date"]
            r["expected"] = hist_event.get("expected", {})

        print_comparison(results)
        all_results.extend(results)

    # Print aggregate summary
    if all_results:
        _print_aggregate_summary(all_results)

    return all_results


def _print_aggregate_summary(all_results: list[dict]):
    """Print aggregate metrics across all backtest events."""
    by_condition: dict[str, list[dict]] = {}
    for r in all_results:
        cond = r.get("condition", "?")
        by_condition.setdefault(cond, []).append(r)

    print(f"\n{'=' * 90}")
    print(f"  AGGREGATE ABLATION SUMMARY ({len(all_results) // 3} events)")
    print(f"{'=' * 90}")

    names = list(by_condition.keys())
    print(f"  {'Metric':<30} " + "".join(f"{n:>20}" for n in names))
    print(f"  {'-' * (30 + 20 * len(names))}")

    for label, key in [("Avg post-debate score", "post_score"),
                        ("Avg HHI", "hhi"),
                        ("Avg elapsed (s)", "elapsed_s")]:
        vals = []
        for name in names:
            results = by_condition[name]
            if key in ("post_score",):
                values = [r.get("benchmark", {}).get(key, 0) for r in results]
            elif key == "hhi":
                values = [r.get(key, 0) for r in results]
            else:
                values = [r.get(key, 0) for r in results]
            avg = sum(values) / len(values) if values else 0
            vals.append(f"{avg:>8.4f}" if key != "elapsed_s" else f"{avg:>7.1f}s")
        print(f"  {label:<30} " + "".join(f"{v:>20}" for v in vals))

    print(f"{'=' * 90}\n")


def main():
    parser = argparse.ArgumentParser(description="Debate Ablation Experiment")
    parser.add_argument("--event", type=str, default=None,
                        help="Event description to analyze")
    parser.add_argument("--budget", type=float, default=1000.0,
                        help="Budget in dollars (default: 1000)")
    parser.add_argument("--lookback-hours", type=int, default=1,
                        help="Lookback window for domain scouts (default: 1)")
    parser.add_argument("--rounds", type=int, default=1,
                        help="Debate rounds for full_debate condition (default: 1)")
    parser.add_argument("--backtest", action="store_true",
                        help="Run on all HISTORICAL_EVENTS from backtest.py")
    parser.add_argument("--init-portfolios", action="store_true",
                        help="Init or rebalance a portfolio profile for each condition")
    args = parser.parse_args()

    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    if args.backtest:
        results = run_backtest_ablation(args.budget, args.rounds)
    else:
        event = args.event or (
            "Run autonomous last-hour change detection across macro, geopolitics, "
            "commodities, market structure, and semiconductor technology updates."
        )
        results = run_ablation(
            event, args.budget, args.lookback_hours, args.rounds,
            init_portfolios=args.init_portfolios,
        )
        print_comparison(results)

    # Save results
    save_ablation_results(results)


def save_ablation_results(results: list[dict]) -> Path:
    """Save ablation results to a timestamped JSON file. Returns the path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = config.DATA_DIR / "debates"
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / f"{timestamp}_ablation_results.json"
    with open(outpath, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to {outpath}")
    return outpath


if __name__ == "__main__":
    main()
