"""
Council of Agents for Causal Reasoning and Portfolio Construction
in the Semiconductor Value Chain.

CLI entry point.

Usage:
    python main.py --event "US announces new AI chip export controls"
    python main.py --event "TSMC raises capex guidance" --company NVDA
    python main.py --phase detect --event "Fed raises rates 25bps"
    python main.py --backtest
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

import config
from agents.pm_agent import PMAgent


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

    args = parser.parse_args()

    if not args.event and not args.backtest:
        parser.print_help()
        print("\nExample:")
        print('  python main.py --event "US Bureau of Industry and Security '
              'announces new export controls restricting sale of advanced AI chips to China"')
        sys.exit(1)

    # Check for API key
    if not config.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set.")
        print("Create a .env file in Final_Project/ with: OPENAI_API_KEY=sk-...")
        sys.exit(1)

    # Initialize PM agent
    print("Initializing Council of Agents...")
    pm = PMAgent()

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
