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
    python main.py --langgraph-alloc --debate-rounds 1               # with 1 debate round
    python main.py --langgraph-alloc --no-analysts                   # PM only (no analyst input)
    python main.py --ablation                                        # debate ablation experiment
    python main.py --ablation --init-portfolios                      # ablation + init portfolio per condition
    python main.py --ablation --backtest                             # ablation on historical events
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
    parser.add_argument(
        '--no-analysts', action='store_true',
        help='Skip company analysts; PM allocates from events + DCF/multiples only'
    )
    parser.add_argument(
        '--ablation', action='store_true',
        help='Run debate ablation experiment (3 conditions: no-analysts, analysts-only, full-debate)'
    )
    parser.add_argument(
        '--init-portfolios', action='store_true',
        help='With --ablation: initialize/rebalance a portfolio for each condition'
    )
    parser.add_argument(
        '--init-live', action='store_true',
        help='Create the live performance Google Sheet and initialize all 4 strategy portfolios'
    )
    parser.add_argument(
        '--sheet-id', type=str, default=None,
        help='With --init-live: use an existing Sheet ID instead of creating a new one'
    )
    parser.add_argument(
        '--live-status', action='store_true',
        help='Print current NAV and return for all live strategy profiles + SPY'
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

    if not args.event and not args.backtest and not args.request_update and not args.langgraph_alloc and not args.ablation and not args.init_live and not args.live_status:
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

    # ── Live experiment: init ──────────────────────────────────────────────────
    if args.init_live:
        from eval.live_performance_sheets import create_performance_sheet, get_sheet_url
        from eval.pm_portfolio import init_portfolio, _trades_path

        print('\n' + '=' * 70)
        print('  INITIALIZING LIVE TRADING EXPERIMENT')
        print('=' * 70)

        # Create or reuse the performance Sheet
        provided_id = getattr(args, 'sheet_id', None)
        if not config.LIVE_PERFORMANCE_SHEET_ID:
            if provided_id:
                print(f'  Scaffolding existing sheet {provided_id}...')
                from eval.live_performance_sheets import scaffold_existing_sheet
                sheet_id = scaffold_existing_sheet(provided_id)
            else:
                print('  Creating Google Sheet...')
                sheet_id = create_performance_sheet()
            # Persist to .env
            env_path = Path(__file__).parent / '.env'
            with open(env_path, 'a') as f:
                f.write(f'\nLIVE_PERFORMANCE_SHEET_ID={sheet_id}\n')
            # Also set in-process so subsequent calls work
            import os as _os
            _os.environ['LIVE_PERFORMANCE_SHEET_ID'] = sheet_id
            config.LIVE_PERFORMANCE_SHEET_ID = sheet_id
            print(f'  Sheet ID saved to .env')
        else:
            print(f'  Using existing sheet: {get_sheet_url()}')

        # Initialize each strategy portfolio with equal-weight allocation
        default_alloc = {'NVDA': 400, 'TSM': 300, 'ASML': 200, 'CDNS': 50, 'CRWV': 50}
        for profile in config.LIVE_STRATEGIES:
            if _trades_path(profile).exists():
                print(f'  [{profile}] Portfolio already exists — skipping init')
            else:
                print(f'  [{profile}] Initializing with {default_alloc}...')
                try:
                    init_portfolio(default_alloc, profile)
                    print(f'  [{profile}] OK')
                except Exception as e:
                    print(f'  [{profile}] ERROR: {e}')

        print(f'\n  Sheet URL: {get_sheet_url()}')
        print('  Run the scheduler with:')
        print('    python eval/live_scheduler.py')
        print('=' * 70 + '\n')
        return

    # ── Live experiment: status ────────────────────────────────────────────────
    if args.live_status:
        from eval.pm_portfolio import get_portfolio_status, _trades_path

        print('\n' + '=' * 70)
        print('  LIVE TRADING STATUS')
        print('=' * 70)

        # SPY
        try:
            spy_path = Path(config.DATA_DIR) / 'benchmarks' / 'spy_shares.txt'
            if spy_path.exists():
                import yfinance as yf
                shares = float(spy_path.read_text().strip())
                hist = yf.Ticker('SPY').history(period='2d')
                spy_price = float(hist['Close'].iloc[-1]) if not hist.empty else 0
                spy_val = round(shares * spy_price, 2)
                spy_ret = round((spy_val / 1000 - 1) * 100, 2)
                print(f'  {"SPY (benchmark)":<20}  ${spy_val:>8.2f}  ({spy_ret:+.2f}%)')
            else:
                print(f'  {"SPY (benchmark)":<20}  not initialized (run --init-live first)')
        except Exception as e:
            print(f'  SPY: error ({e})')

        for profile, cfg in config.LIVE_STRATEGIES.items():
            if not _trades_path(profile).exists():
                print(f'  {profile:<20}  not initialized')
                continue
            try:
                s = get_portfolio_status(profile)
                val = s.get('portfolio_value', 0)
                ret = s.get('return_pct', 0) * 100
                n = s.get('trades_count', 0)
                last = s.get('last_date', '—')
                print(f'  {profile:<20}  ${val:>8.2f}  ({ret:+.2f}%)  '
                      f'{n} trades  last: {last}')
            except Exception as e:
                print(f'  {profile:<20}  error ({e})')

        from eval.live_performance_sheets import get_sheet_url
        url = get_sheet_url()
        if url:
            print(f'\n  Sheets: {url}')
        print('=' * 70 + '\n')
        return

    # Debate ablation experiment
    if args.ablation:
        from eval.debate_ablation import (
            run_ablation, run_backtest_ablation, print_comparison,
            save_ablation_results,
        )
        init_p = getattr(args, "init_portfolios", False)
        if args.backtest:
            results = run_backtest_ablation(args.budget, args.debate_rounds or 1)
        else:
            event = args.event or ""
            results = run_ablation(
                event, args.budget, args.lookback_hours, args.debate_rounds or 1,
                init_portfolios=init_p,
            )
            print_comparison(results)
        save_ablation_results(results)
        return

    # LangGraph allocation pipeline (runs graph directly; no full PM init needed)
    if args.langgraph_alloc:
        from langgraph_pipeline import graph
        print("\n" + "=" * 70)
        print("  LANGGRAPH ALLOCATION PIPELINE (local)")
        print("=" * 70)
        debate_mode = f"{getattr(args, 'debate_rounds', 0)}-round debate" if getattr(args, 'debate_rounds', 0) > 0 else "one-shot"
        analysts_mode = "NO ANALYSTS" if getattr(args, "no_analysts", False) else "with analysts"
        print(f"  Budget: ${args.budget:.0f}  |  Lookback: {args.lookback_hours}h  |  Debate: {debate_mode}  |  Analysts: {analysts_mode}  |  Event: {args.event or '(autonomous)'}\n")
        state = {
            "event": args.event or "",
            "lookback_hours": args.lookback_hours,
            "budget": args.budget,
            "debate_rounds": getattr(args, "debate_rounds", 0),
            "no_analysts": getattr(args, "no_analysts", False),
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
