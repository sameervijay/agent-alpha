"""
Council of Agents for Causal Reasoning and Portfolio Construction
in the Semiconductor Value Chain.

CLI entry point.

Usage:
    python main.py                                      # default: PM-led allocation ($1000, last 1h, autonomous)
    python main.py --event "US announces new AI chip export controls"
    python main.py --event "TSMC raises capex guidance" --company NVDA
    python main.py --phase detect --event "Fed raises rates 25bps"
    python main.py --backtest
    python main.py --langgraph-alloc                    # PM-led allocation ($1000, last 1h)
    python main.py --langgraph-alloc --budget 500 --event "Focus on Fed"
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root and config/ subdirectory are on path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'config'))

import config


def _load_pm():
    """Return the PMAgent class (LangChain)."""
    from agents_langchain.pm_agent import PMAgent
    return PMAgent


def main():
    parser = argparse.ArgumentParser(
        description="Council of Agents — Semiconductor Valuation Pipeline"
    )
    parser.add_argument(
        '--event', type=str,
        help='Event description to analyze (e.g., "US announces new export controls")'
    )
    parser.add_argument(
        '--company', type=str, default='NVDA',
        choices=list(config.COMPANIES.keys()),
        help='Target company ticker (default: NVDA)'
    )
    parser.add_argument(
        '--phase', type=str, default='all',
        choices=['detect', 'causal', 'debate', 'value', 'all'],
        help='Run specific phase or all (default: all)'
    )
    parser.add_argument(
        '--backtest', action='store_true',
        help='Run historical event backtesting'
    )
    parser.add_argument(
        '--sensitivity', action='store_true',
        help='Run WACC sensitivity analysis after valuation'
    )
    parser.add_argument(
        '--request-update', action='store_true',
        help='PM initiates a focused update dialogue with company analyst (no --event needed)'
    )
    parser.add_argument(
        '--langgraph-alloc', action='store_true',
        help='Run LangGraph PM-led allocation pipeline (domain scouts → company analysts → debate → $ allocation)'
    )
    parser.add_argument(
        '--langgraph-panel-alloc', action='store_true',
        help='Run LangGraph PM-led allocation pipeline with single-shot PM panel synthesis (no multi-round debate)'
    )
    parser.add_argument(
        '--budget', type=float, default=1000.0,
        help='Fixed budget in dollars for --langgraph-alloc (default: 1000)'
    )
    parser.add_argument(
        '--lookback-hours', type=int, default=1,
        help='Lookback window in hours for domain scouts (default: 1)'
    )
    parser.add_argument(
        '--debate-rounds', type=int, default=0,
        help='Number of cross-analyst challenge rounds before PM allocates (0=one-shot, default; 1-3=round-by-round)'
    )

    args = parser.parse_args()

    # Default behavior: no CLI arguments → LangGraph allocation pipeline
    # with standard PM-led settings ($1000 budget, last 1h, autonomous event).
    if len(sys.argv) == 1:
        args.langgraph_alloc = True
        args.budget = 1000.0
        args.lookback_hours = 1
        args.event = None
        args.debate_rounds = 0

    if (
        not args.event
        and not args.backtest
        and not args.request_update
        and not args.langgraph_alloc
        and not args.langgraph_panel_alloc
    ):
        parser.print_help()
        print("\nExample:")
        print('  python main.py --event "US Bureau of Industry and Security '
              'announces new export controls restricting sale of advanced AI chips to China"')
        print('  python main.py --request-update --company NVDA')
        sys.exit(1)

    # Check for API key
    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set.")
        print("Create a .env file in Final_Project/ with: OPENAI_API_KEY=sk-...")
        sys.exit(1)

    # LangGraph allocation pipelines (run graph directly; no full PM init needed)
    if args.langgraph_panel_alloc:
        from langgraph_pipeline_panel import graph_panel
        print("\n" + "=" * 70)
        print("  LANGGRAPH ALLOCATION PIPELINE (local, PANEL SYNTHESIS)")
        print("=" * 70)
        print(
            f"  Budget: ${args.budget:.0f}  |  Lookback: {args.lookback_hours}h  |  "
            f"Mode: panel-synthesis  |  Event: {args.event or '(autonomous)'}\n"
        )
        state = {
            "event": args.event or "",
            "lookback_hours": args.lookback_hours,
            "budget": args.budget,
            # debate_rounds is ignored by the panel pipeline but included for consistency
            "debate_rounds": getattr(args, "debate_rounds", 0),
        }
        out = graph_panel.invoke(state)
        if out.get("error"):
            print(f"  Error: {out['error']}\n")
            sys.exit(1)
        result = out.get("result", {})
        alloc = result.get("allocation_dollars", {})
        print("  ALLOCATION (dollars):")
        for ticker, dollars in sorted(alloc.items(), key=lambda x: -x[1]):
            pct = result.get("allocation_pct", {}).get(ticker, 0) * 100
            print(f"    {ticker}: ${dollars:.2f}  ({pct:.1f}%)")
        print(f"  Total: ${sum(alloc.values()):.2f}")
        if result.get("rationale"):
            print(f"\n  Rationale: {result['rationale'][:400]}...")
        if result.get("errors"):
            print(f"\n  Warnings: {result['errors']}")
        print("=" * 70 + "\n")
        return

    if args.langgraph_alloc:
        from langgraph_pipeline import graph
        print("\n" + "=" * 70)
        print("  LANGGRAPH ALLOCATION PIPELINE (local)")
        print("=" * 70)
        debate_mode = f"{getattr(args, 'debate_rounds', 0)}-round debate" if getattr(args, 'debate_rounds', 0) > 0 else "one-shot"
        print(f"  Budget: ${args.budget:.0f}  |  Lookback: {args.lookback_hours}h  |  Debate: {debate_mode}  |  Event: {args.event or '(autonomous)'}\n")
        state = {
            "event": args.event or "",
            "lookback_hours": args.lookback_hours,
            "budget": args.budget,
            "debate_rounds": getattr(args, "debate_rounds", 0),
        }
        out = graph.invoke(state)
        if out.get("error"):
            print(f"  Error: {out['error']}\n")
            sys.exit(1)
        result = out.get("result", {})
        alloc = result.get("allocation_dollars", {})
        print("  ALLOCATION (dollars):")
        for ticker, dollars in sorted(alloc.items(), key=lambda x: -x[1]):
            pct = result.get("allocation_pct", {}).get(ticker, 0) * 100
            print(f"    {ticker}: ${dollars:.2f}  ({pct:.1f}%)")
        print(f"  Total: ${sum(alloc.values()):.2f}")
        if result.get("rationale"):
            print(f"\n  Rationale: {result['rationale'][:400]}...")
        if result.get("errors"):
            print(f"\n  Warnings: {result['errors']}")
        print("=" * 70 + "\n")
        return

    # Initialize PM agent (LangChain)
    print("\n" + "=" * 70)
    print("  INITIALIZING COUNCIL OF AGENTS  [LangChain]")
    print("=" * 70)
    PMAgent = _load_pm()
    pm = PMAgent()
    print("  Initialization complete.\n")

    if args.request_update:
        session = pm.request_update(args.company)
        return

    if args.backtest:
        from eval.backtest import run_backtest, print_backtest_summary
        results = run_backtest(pm)
        print_backtest_summary(results)
        return

    # Run pipeline based on phase
    if args.phase == 'all':
        result = pm.run_full_pipeline(args.event, target_company=args.company)

        # Optional sensitivity analysis
        if args.sensitivity and args.company in pm.engines:
            from valuation.sensitivity import (wacc_sensitivity, signal_stability,
                                                print_wacc_table)
            engine = pm.engines[args.company]
            wacc_results = wacc_sensitivity(engine)
            print_wacc_table(wacc_results)
            stability = signal_stability(wacc_results)
            if stability['re_debate_required']:
                print("  WARNING: Signal is UNSTABLE across WACC range.")
                print(f"  Signals observed: {stability['signals_in_range']}")
                print("  Consider re-debating with tighter driver assumptions.\n")
            else:
                print(f"  Signal is STABLE: {stability['signal']} across WACC range.\n")

    elif args.phase == 'detect':
        events = pm.detect_events(args.event)
        print(f"\nDetected {len(events)} events.")

    elif args.phase == 'causal':
        events = pm.detect_events(args.event)
        if events:
            graph = pm.build_causal_graph(events[0])
            print(f"\nCausal graph: {len(graph.links)} links, "
                  f"{len(graph.get_conflicts())} conflicts")

    elif args.phase == 'debate':
        events = pm.detect_events(args.event)
        if events:
            graph = pm.build_causal_graph(events[0])
            target_links = graph.get_links_for_company(args.company)
            if target_links:
                from models.causal_graph import CausalGraph
                target_graph = CausalGraph(
                    event_id=events[0].id,
                    event_headline=events[0].headline,
                    links=target_links,
                )
                session = pm.run_debate(events[0], target_graph)
                print(f"\nDebate: {len(session.rounds)} rounds, "
                      f"{len(session.resolutions)} resolutions")

    elif args.phase == 'value':
        events = pm.detect_events(args.event)
        if events:
            graph = pm.build_causal_graph(events[0])
            target_links = graph.get_links_for_company(args.company)
            if target_links:
                from models.causal_graph import CausalGraph
                target_graph = CausalGraph(
                    event_id=events[0].id,
                    event_headline=events[0].headline,
                    links=target_links,
                )
                session = pm.run_debate(events[0], target_graph)
                result = pm.apply_to_dcf(args.company, session)


if __name__ == '__main__':
    main()
