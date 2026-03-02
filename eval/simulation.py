"""
eval/simulation.py — Historical event simulation and accuracy benchmark for Agent Alpha.

Runs the LangGraph allocation pipeline against known historical events in three modes:
  dr=0  — One-shot (no cross-analyst debate)
  dr=2  — 2-round cross-analyst debate
  dr=4  — 4-round cross-analyst debate

For each mode, fetches actual stock prices via yfinance and calculates realized P&L
over 5/10/20-day holding windows versus SPY (S&P 500 benchmark).

Outputs:
  - Per-event allocation table (all three modes side-by-side)
  - Realized return table with alpha decomposition
  - Pairwise mode deltas (2-round vs one-shot, 4-round vs 2-round, etc.)
  - Aggregate summary across events with beat-rates and mode rankings

Results are cached to data/simulations/ so the expensive LLM pipeline only runs once.
Force a re-run with --force-rerun.

METHODOLOGY NOTE:
  The agents use live news APIs (current date) plus the injected event description.
  This means domain scouts may also surface current news alongside the historical event.
  Treat results as "event-conditioned simulation" not a fully clean historical backtest.

Usage:
    .venv/Scripts/python.exe eval/simulation.py
    .venv/Scripts/python.exe eval/simulation.py --modes 0 2 4
    .venv/Scripts/python.exe eval/simulation.py --event-id deepseek_shock
    .venv/Scripts/python.exe eval/simulation.py --force-rerun
    .venv/Scripts/python.exe eval/simulation.py --no-pipeline   # prices + cached only
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import config  # noqa: E402

# ── Debate modes ───────────────────────────────────────────────────────────────
DEFAULT_MODES = [0, 2]
MODE_LABELS: dict[int, str] = {0: "One-shot", 2: "2-round", 4: "4-round"}

def _mode_label(m: int) -> str:
    return MODE_LABELS.get(m, f"dr={m}")

# ── Historical events ──────────────────────────────────────────────────────────
EVENTS: list[dict] = [
    {
        "id": "nvda_ai_earnings_blowout",
        "name": "NVIDIA Q2 FY2024 AI Earnings Blowout",
        "event_date": "2023-08-24",
        "description": (
            "NVIDIA reports Q2 FY2024 results after market close on August 23, 2023: "
            "revenue $13.51B vs $11.22B consensus, data center revenue $10.32B (doubled sequentially). "
            "Q3 guidance set at $16.0B vs $12.5B consensus — the largest ever beat-and-raise in "
            "semiconductor history. CEO Jensen Huang calls H100 GPU demand 'insane' across hyperscalers. "
            "NVIDIA stock surges 8% at open. AI infrastructure buildout narrative firmly established: "
            "TSM is sole H100 manufacturer, ASML EUV tools are on the critical path, CDNS EDA tools "
            "are essential for next-gen AI chip design. CoreWeave (pre-IPO) GPU fleet utilization spikes "
            "as enterprise AI demand overwhelms available H100 supply."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "asml_booking_miss",
        "name": "ASML Q1 2024 Bookings Miss — EUV Demand Shock",
        "event_date": "2024-04-17",
        "description": (
            "ASML Holding accidentally publishes Q1 2024 earnings one day early (April 16), "
            "then officially reports April 17: net bookings of €3.61B, massively below €4.6B "
            "consensus. EUV bookings fall to €1.23B from €9.2B in Q4 2023. Management cites order "
            "lumpiness and customer inventory digestion in memory. ASML shares drop 7% intraday, "
            "dragging TSM, NVDA, and CDNS lower. Market questions whether memory capex recovery "
            "has stalled and whether AI-logic demand alone can sustain equipment spending at "
            "prior pace. NVIDIA supply chain scrutinized: if TSMC delays N3/N2 capex due to "
            "equipment delivery timelines, H100/B100 production ramp could slip."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "deepseek_shock",
        "name": "DeepSeek R1 Release — AI Demand Disruption",
        "event_date": "2025-01-27",
        "description": (
            "DeepSeek releases R1, a Chinese open-source AI model matching GPT-4 performance "
            "at a fraction of the training compute cost, raising serious questions about whether "
            "AI hyperscalers will reduce GPU orders. NVIDIA stock drops 17% intraday. "
            "Advanced packaging (CoWoS) demand outlook becomes uncertain. "
            "Market debates whether AI training efficiency gains will structurally reduce "
            "datacenter GPU demand for NVIDIA, TSM, and ASML."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    # ── 7 additional events ────────────────────────────────────────────────────
    {
        "id": "nvda_q4fy23_first_ai_signal",
        "name": "NVIDIA Q4 FY2023 — First ChatGPT/AI Demand Signal",
        "event_date": "2023-02-23",
        "description": (
            "NVIDIA reports Q4 FY2023 (January quarter) after close on Feb 22, 2023: "
            "revenue $6.05B in-line but Q1 FY2024 guidance of $6.5B ± 2% versus $6.35B consensus. "
            "CEO Jensen Huang explicitly cites 'accelerating demand for AI and ChatGPT-like applications' "
            "as a new datacenter demand driver — the first such language on an NVDA earnings call. "
            "Data center revenue $3.62B, gaming still de-stocking but recovering. "
            "NVIDIA stock surges 13% on Feb 23 open as the market begins pricing in an AI infrastructure "
            "buildout: TSMC as sole H100 manufacturer, ASML EUV on the critical path, CDNS EDA tools "
            "essential for hyperscaler AI ASIC programs. This is the inflection-point print before "
            "the Q2 FY2024 blowout — a smaller but directionally clean beat-and-raise."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "tsmc_capex_cut_2022",
        "name": "TSMC Q3 2022 Earnings — Capex Cut Signals Equipment Downturn",
        "event_date": "2022-10-13",
        "description": (
            "TSMC reports Q3 2022 earnings: revenue NT$613B (+35.9% YoY), beats consensus, "
            "but sharply cuts full-year 2022 capex guidance to ~$36B from prior $40-44B range — "
            "the first capex reduction since 2019. Management cites weakening smartphone/PC demand, "
            "elevated customer inventory, and desire to preserve cash amid demand uncertainty. "
            "N3 (3nm) ramp on track but N2 timeline pushed. "
            "ASML is the direct casualty: EUV tool deliveries likely to be deferred into 2023-2024, "
            "threatening ASML booking momentum. CDNS faces lower near-term tape-out volume as "
            "foundry utilization drops below 90%. NVIDIA not directly impacted (data center demand "
            "still robust from hyperscalers) but the capex discipline narrative raises concern about "
            "AI accelerator supply if discipline persists into 2023. Intel also cutting orders, "
            "compounding ASML booking headwinds. Semi equipment stocks broadly re-rate lower."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "us_china_chip_controls_oct23",
        "name": "BIS Expands AI Chip Export Controls — A800/H800 Banned",
        "event_date": "2023-10-17",
        "description": (
            "US Bureau of Industry and Security (BIS) announces expanded semiconductor export "
            "controls effective immediately: NVIDIA A800 and H800 — chips specifically designed to "
            "comply with prior August 2022 restrictions — are now banned for export to China. "
            "New performance density thresholds close the loophole that allowed NVDA to sell "
            "China-specific variants. NVIDIA China revenue estimated at $2.0-2.5B annually is "
            "now at acute risk. Huawei Ascend 910B positioned as domestic Chinese alternative. "
            "TSMC manufacturing of advanced node chips for Chinese AI firms faces heightened scrutiny. "
            "ASML's EUV tools already cannot export to China; additional DUV restrictions discussed. "
            "CDNS EDA software licenses to Chinese chip firms also under compliance review. "
            "NVIDIA stock drops 4-5% on the announcement. The market debates whether China revenue "
            "loss is already priced in versus the signal of escalating US-China technology decoupling."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "tsmc_q3_2023_soft_guide",
        "name": "TSMC Q3 2023 Earnings — Revenue Decline, Cautious 2024 Capex",
        "event_date": "2023-10-19",
        "description": (
            "TSMC reports Q3 2023: revenue NT$546.7B, down 10.8% YoY — steepest annual decline "
            "in over a decade, driven by smartphone/PC inventory digestion. Gross margin 54.3%, "
            "down from 59.8% a year ago due to lower utilization rates. Q4 2023 guidance of "
            "$18.8-19.6B (USD) roughly in-line but cautious. Full-year 2023 capex guided to "
            "'slightly below' $32B (prior guidance $32-36B). Management: N3 ramp proceeding, "
            "N2 (2nm) delayed to H2 2025. HPC segment (AI/datacenter) now 42% of revenue and "
            "sole growth driver; smartphone 35%. ASML read-through: TSMC capex discipline means "
            "EUV orders back-loaded into 2024; near-term order visibility worsens. NVIDIA H100 "
            "supply on N3 on track but capacity for B100 Blackwell (2025) still unconfirmed. "
            "CDNS: chiplet designs and 3D-IC proliferating, supporting EDA tool demand despite "
            "lower tape-out volumes. Overall a cautious print that challenges the AI-drives-all "
            "capex narrative."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "nvda_q1fy25_blackwell_reveal",
        "name": "NVIDIA Q1 FY2025 Earnings + Blackwell Architecture Reveal",
        "event_date": "2024-05-23",
        "description": (
            "NVIDIA reports Q1 FY2025 (April quarter) after close on May 22, 2024: revenue "
            "$26.04B vs $24.59B consensus (+262% YoY), data center $22.6B vs $21.1B consensus — "
            "the highest single-quarter data center revenue in semiconductor history at the time. "
            "Q2 FY2025 guidance of $28.0B ± 2% vs $26.6B consensus. Gross margin 78.9% vs 77.1% "
            "consensus. $10B share buyback authorized. Blackwell GPU architecture confirmed: "
            "B100/B200 GPUs deliver 4x training and 30x inference speedup over H100, with "
            "production ramp beginning Q2 2024. CoWoS advanced packaging demand at TSMC set to "
            "double in 2024. ASML EUV tools required for B100 at TSMC N4P — order books extending "
            "into 2025. CDNS EDA tools essential for Blackwell chiplet architecture design. "
            "NVIDIA stock surges 10% on May 23. CoreWeave (pre-IPO) GPU contract utilization near 100%."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "nvda_q3fy25_margin_concern",
        "name": "NVIDIA Q3 FY2025 Earnings — Revenue Beat, Gross Margin Miss",
        "event_date": "2024-11-21",
        "description": (
            "NVIDIA reports Q3 FY2025 (October quarter) after close on Nov 20, 2024: revenue "
            "$35.08B vs $33.17B consensus (+94% YoY), data center $30.8B — beats on revenue. "
            "However, gross margin 74.6% misses the 75.0% guidance midpoint and 75.1% consensus, "
            "driven by Blackwell GPU manufacturing complexity and CoWoS packaging costs at TSMC. "
            "Q4 FY2025 guidance of $37.5B ± 2% vs $37.1B consensus — a small beat. CFO warns "
            "Blackwell supply will remain 'tight' through Q1 FY2026 due to CoWoS constraints. "
            "NVIDIA stock falls 3% after hours then partially recovers. Market concern: compressed "
            "Blackwell gross margins may be structural rather than transient. TSMC CoWoS capacity "
            "is the binding constraint. ASML EUV demand robust as Blackwell uses N4P. "
            "CDNS: Blackwell chiplet complexity drives EDA tool spending. "
            "CoreWeave (pre-IPO): Blackwell allocation highly sought; tight supply limits expansion plans."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV pre-IPO (IPO March 28 2025) — excluded; weight redistributed to remaining tickers",
        "exclude_tickers": ["CRWV"],
    },
    {
        "id": "liberation_day_tariffs",
        "name": "Liberation Day Tariffs — Semiconductor Supply Chain Shock",
        "event_date": "2025-04-03",
        "description": (
            "President Trump announces 'Liberation Day' tariffs after market close on April 2, 2025: "
            "10% baseline tariff on all imports, 145% tariff on Chinese goods, 32% tariff on Taiwan "
            "(subsequently paused for 90 days). Semiconductors initially exempted from highest tiers "
            "but face 10% baseline plus uncertainty. Markets open sharply lower on April 3: "
            "NVDA -7%, TSM -8%, ASML -5%, CDNS -4%. "
            "Key concerns: TSMC Arizona fab economics worsen if Taiwan tariffs resume; "
            "NVIDIA China revenue already restricted but supply chain costs rise; "
            "ASML has globally distributed supply chain (German optics, Dutch assembly) — "
            "system costs rise with each tariff layer; "
            "CDNS software licensing is largely tariff-immune but hardware acceleration impacted; "
            "CoreWeave GPU import costs could increase if NVIDIA passes through tariff pressure. "
            "The tariff shock resets near-term capex expectations across the semiconductor supply chain."
        ),
        "holding_days": [5, 10, 20],
        "note": "CRWV post-IPO (IPO March 28 2025) — included",
        "exclude_tickers": [],
    },
]

HOLDING_DAYS = [5, 10, 20]
BENCHMARK = "SPY"
CACHE_DIR = _ROOT / "data" / "simulations"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Price fetching ─────────────────────────────────────────────────────────────

def fetch_event_prices(
    tickers: list[str],
    event_date: str,
    max_holding: int = 25,
) -> dict[str, dict[int, float]]:
    """Fetch close prices at T+0, T+5, T+10, T+20 for each ticker.

    Returns {ticker: {offset_days: close_price}}.
    Uses the first available trading day on or after each target date.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  [sim] yfinance not available — install with: pip install yfinance")
        return {}

    start_dt = datetime.strptime(event_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=max_holding + 15)
    all_tickers = list(dict.fromkeys(tickers + [BENCHMARK]))  # deduplicate, preserve order

    result: dict[str, dict[int, float]] = {}
    print(f"  [sim] Fetching prices {event_date} → {end_dt.strftime('%Y-%m-%d')} "
          f"for {len(all_tickers)} tickers...")

    for ticker in all_tickers:
        try:
            hist = yf.Ticker(ticker).history(
                start=start_dt.strftime("%Y-%m-%d"),
                end=end_dt.strftime("%Y-%m-%d"),
            )
            if hist.empty:
                print(f"  [sim] {ticker}: no price data (pre-IPO or delisted)")
                continue
            prices_at: dict[int, float] = {}
            for offset in [0] + HOLDING_DAYS:
                target = start_dt + timedelta(days=offset)
                available = hist[hist.index.normalize() >= target.strftime("%Y-%m-%d")]
                if available.empty:
                    continue
                prices_at[offset] = round(float(available["Close"].iloc[0]), 4)
            if prices_at:
                result[ticker] = prices_at
        except Exception as exc:
            print(f"  [sim] {ticker} price fetch error: {exc}")

    return result


def pct_return(prices: dict[int, float], holding: int) -> float | None:
    """Fractional return from T+0 to T+holding."""
    p0 = prices.get(0)
    pt = prices.get(holding)
    if p0 is None or pt is None or p0 == 0:
        return None
    return (pt - p0) / p0


# ── Pipeline runner ────────────────────────────────────────────────────────────

def run_pipeline(event_desc: str, debate_rounds: int, budget: float) -> dict:
    """Invoke the LangGraph graph and return the result dict."""
    from langgraph_pipeline import graph  # import here to avoid slow load at module level
    state = {
        "event": event_desc,
        "lookback_hours": 1,
        "budget": budget,
        "debate_rounds": debate_rounds,
    }
    out = graph.invoke(state)
    return out.get("result", {})


def load_or_run(
    event: dict,
    debate_rounds: int,
    budget: float,
    force_rerun: bool,
) -> dict:
    """Load cached pipeline output or run fresh."""
    cache = CACHE_DIR / f"{event['id']}_dr{debate_rounds}.json"
    if cache.exists() and not force_rerun:
        print(f"  [sim] Using cached pipeline output: {cache.name}")
        with open(cache) as f:
            return json.load(f)
    print(f"  [sim] Running pipeline — event={event['id']}, debate_rounds={debate_rounds}")
    result = run_pipeline(event["description"], debate_rounds, budget)
    with open(cache, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"  [sim] Saved → {cache.name}")
    return result


# ── Portfolio return calculation ───────────────────────────────────────────────

def portfolio_return(
    allocation_dollars: dict[str, float],
    prices: dict[str, dict[int, float]],
    holding: int,
    exclude: list[str],
) -> float | None:
    """Portfolio return = weighted average of individual stock returns.
    Excluded tickers have their weight proportionally redistributed.
    """
    excl = set(exclude)
    eligible = {
        t: v for t, v in allocation_dollars.items()
        if t not in excl and t in prices and prices[t].get(0) is not None
    }
    total = sum(eligible.values())
    if total <= 0:
        return None
    port_ret = 0.0
    for ticker, dollars in eligible.items():
        ret = pct_return(prices[ticker], holding)
        if ret is None:
            continue
        port_ret += (dollars / total) * ret
    return port_ret


# ── Reporting ──────────────────────────────────────────────────────────────────

def _fp(v: float | None, decimals: int = 2) -> str:
    """Format a fractional return as percentage string."""
    if v is None:
        return "    N/A "
    return f"{v:+8.{decimals}%}"


def _alpha(a: float | None, b: float | None) -> float | None:
    return (a - b) if (a is not None and b is not None) else None


def print_event_report(
    event: dict,
    prices: dict[str, dict[int, float]],
    mode_results: dict[int, dict],
) -> dict:
    """Print full event report comparing all modes. Returns structured results dict.

    mode_results: {debate_rounds: pipeline_result_dict}
    """
    excl = event.get("exclude_tickers", [])
    sorted_modes = sorted(mode_results.keys())
    budget = next(iter(mode_results.values())).get("budget", 1000.0)

    print(f"\n{'═'*72}")
    print(f"  EVENT: {event['name']}")
    print(f"  Date:  {event['event_date']}   Budget: ${budget:.0f}")
    if event.get("note"):
        print(f"  Note:  {event['note']}")
    print(f"{'═'*72}")

    # ── Allocations side-by-side ──
    hdr_cells = "  ".join(f"{_mode_label(m):>12}" for m in sorted_modes)
    print(f"\n  {'Ticker':<8}  {hdr_cells}")
    print(f"  {'─'*52}")
    for t in config.COMPANIES:
        vals = "  ".join(
            f"${mode_results[m].get('allocation_dollars', {}).get(t, 0):>10.0f}"
            for m in sorted_modes
        )
        excl_flag = "  *" if t in excl else ""
        print(f"  {t:<8}  {vals}{excl_flag}")
    if excl:
        print(f"  (* excluded pre-IPO — weight redistributed)")

    # ── Per-ticker price snapshot ──
    print(f"\n  Price snapshot ({event['event_date']} = T+0):")
    print(f"  {'Ticker':<8}  {'T+0':>8}  {'T+5':>8}  {'T+10':>8}  {'T+20':>8}")
    print(f"  {'─'*52}")
    display_tickers = [t for t in list(config.COMPANIES.keys()) + [BENCHMARK] if t in prices]
    for t in display_tickers:
        p = prices[t]
        vals = "  ".join(
            f"${p.get(h, 0):>7.2f}" if p.get(h) else "      N/A"
            for h in [0, 5, 10, 20]
        )
        flag = "*" if t in excl else " "
        print(f"  {t:<8}{flag} {vals}")

    # ── Compute returns ──
    spy_rets = {h: pct_return(prices.get(BENCHMARK, {}), h) for h in HOLDING_DAYS}
    mode_rets: dict[int, dict[int, float | None]] = {}
    for m in sorted_modes:
        alloc = mode_results[m].get("allocation_dollars", {})
        mode_rets[m] = {h: portfolio_return(alloc, prices, h, excl) for h in HOLDING_DAYS}

    # ── Returns table ──
    col_hdr = "  ".join(f"{'T+'+str(h):>8}" for h in HOLDING_DAYS)
    print(f"\n  {'Strategy':<30}  {col_hdr}")
    print(f"  {'─'*58}")

    def row(label: str, rets: dict) -> None:
        vals = "  ".join(_fp(rets.get(h)) for h in HOLDING_DAYS)
        print(f"  {label:<30}  {vals}")

    row("SPY (benchmark)", spy_rets)
    for m in sorted_modes:
        row(_mode_label(m), mode_rets[m])

    print(f"  {'─'*58}")

    # Alpha vs SPY for each mode
    mode_alpha_spy: dict[int, dict[int, float | None]] = {}
    for m in sorted_modes:
        mode_alpha_spy[m] = {h: _alpha(mode_rets[m].get(h), spy_rets.get(h)) for h in HOLDING_DAYS}
        row(f"α: {_mode_label(m)} vs SPY", mode_alpha_spy[m])

    # Pairwise alpha between consecutive modes
    print(f"  {'─'*58}")
    pairwise: dict[tuple[int, int], dict[int, float | None]] = {}
    for i in range(1, len(sorted_modes)):
        m_hi, m_lo = sorted_modes[i], sorted_modes[i - 1]
        delta = {h: _alpha(mode_rets[m_hi].get(h), mode_rets[m_lo].get(h)) for h in HOLDING_DAYS}
        pairwise[(m_hi, m_lo)] = delta
        row(f"α: {_mode_label(m_hi)} vs {_mode_label(m_lo)}", delta)

    # ── Conv×Upside scores ──
    score_parts = []
    for m in sorted_modes:
        bm = mode_results[m].get("benchmark", {})
        pre = bm.get("pre_score")
        post = bm.get("post_score")
        if pre is not None and post is not None:
            score_parts.append(f"{_mode_label(m)}: pre={pre:.4f} post={post:.4f}")
    if score_parts:
        print(f"\n  Conv×Upside: {' | '.join(score_parts)}")

    # ── Build structured result ──
    result = {
        "event_id":   event["id"],
        "event_name": event["name"],
        "spy":        spy_rets,
        "modes": {
            m: {
                "label":         _mode_label(m),
                "rets":          mode_rets[m],
                "alpha_vs_spy":  mode_alpha_spy[m],
                "alloc":         mode_results[m].get("allocation_dollars", {}),
            }
            for m in sorted_modes
        },
        "pairwise": {
            f"{m_hi}_vs_{m_lo}": delta
            for (m_hi, m_lo), delta in pairwise.items()
        },
    }

    report_path = CACHE_DIR / f"{event['id']}_report.json"
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n  Report saved → {report_path.relative_to(_ROOT)}")
    return result


def print_summary(results: list[dict], sorted_modes: list[int]) -> None:
    """Cross-event aggregate summary."""
    n = len(results)
    print(f"\n{'═'*72}")
    print(f"  AGGREGATE BENCHMARK SUMMARY")
    print(f"  ({n} events | modes: {[_mode_label(m) for m in sorted_modes]})")
    print(f"{'═'*72}")

    def avg_spy(h: int) -> float | None:
        vals = [r["spy"].get(h) for r in results if r["spy"].get(h) is not None]
        return sum(vals) / len(vals) if vals else None

    def avg_mode(m: int, h: int) -> float | None:
        vals = [
            r["modes"][m]["rets"].get(h)
            for r in results
            if m in r.get("modes", {}) and r["modes"][m]["rets"].get(h) is not None
        ]
        return sum(vals) / len(vals) if vals else None

    col_hdr = "  ".join(f"{'T+'+str(h):>8}" for h in HOLDING_DAYS)
    print(f"\n  {'Strategy':<30}  {col_hdr}")
    print(f"  {'─'*58}")

    def row(label: str, fn) -> None:
        vals = "  ".join(_fp(fn(h)) for h in HOLDING_DAYS)
        print(f"  {label:<30}  {vals}")

    row("SPY avg return", avg_spy)
    for m in sorted_modes:
        row(f"{_mode_label(m)} avg return", lambda h, m=m: avg_mode(m, h))

    print(f"  {'─'*58}")
    # Alpha vs SPY
    for m in sorted_modes:
        def alpha_spy_fn(h, m=m):
            mr = avg_mode(m, h)
            sr = avg_spy(h)
            return _alpha(mr, sr)
        row(f"Avg α: {_mode_label(m)} vs SPY", alpha_spy_fn)

    # Pairwise between consecutive modes
    print(f"  {'─'*58}")
    for i in range(1, len(sorted_modes)):
        m_hi, m_lo = sorted_modes[i], sorted_modes[i - 1]
        def pairwise_fn(h, m_hi=m_hi, m_lo=m_lo):
            return _alpha(avg_mode(m_hi, h), avg_mode(m_lo, h))
        row(f"Avg α: {_mode_label(m_hi)} vs {_mode_label(m_lo)}", pairwise_fn)

    # Beat-rate vs SPY at T+20
    print(f"\n  Beat-rate at T+20 (vs SPY):")
    for m in sorted_modes:
        beats = sum(
            1 for r in results
            if m in r.get("modes", {}) and (r["modes"][m]["alpha_vs_spy"].get(20) or 0) > 0
        )
        print(f"    {_mode_label(m):<20}: {beats}/{n} ({beats/n:.0%})")

    # Mode ranking at T+20 by average alpha vs SPY
    print(f"\n  Mode ranking at T+20 (avg α vs SPY):")
    rankings = []
    for m in sorted_modes:
        avg_a = sum(
            (r["modes"].get(m, {}).get("alpha_vs_spy", {}).get(20) or 0)
            for r in results
            if m in r.get("modes", {})
        ) / max(n, 1)
        rankings.append((m, avg_a))
    rankings.sort(key=lambda x: x[1], reverse=True)
    for rank, (m, avg_a) in enumerate(rankings, 1):
        print(f"    #{rank}  {_mode_label(m):<20}: avg α = {avg_a:+.2%}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent Alpha historical event simulation and benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Events available:
  deepseek_shock   — DeepSeek R1 release, Jan 27 2025 (NVDA -17%)
  liberation_day   — Trump Liberation Day tariffs, Apr 3 2025

Examples:
  .venv/Scripts/python.exe eval/simulation.py
  .venv/Scripts/python.exe eval/simulation.py --modes 0 2 4
  .venv/Scripts/python.exe eval/simulation.py --event-id deepseek_shock --force-rerun
  .venv/Scripts/python.exe eval/simulation.py --no-pipeline   # skip pipeline, use cache only
        """,
    )
    parser.add_argument(
        "--modes", type=int, nargs="+", default=DEFAULT_MODES,
        help=f"Debate round counts to compare (default: {DEFAULT_MODES})",
    )
    parser.add_argument("--budget", type=float, default=1000.0,
                        help="Portfolio budget in dollars (default: 1000)")
    parser.add_argument("--force-rerun", action="store_true",
                        help="Re-run pipeline even if cached results exist")
    parser.add_argument("--no-pipeline", action="store_true",
                        help="Skip pipeline run, use cached results only (error if cache missing)")
    parser.add_argument("--event-id", type=str, default=None,
                        help="Run only a specific event by ID")
    args = parser.parse_args()

    sorted_modes = sorted(set(args.modes))
    events = [e for e in EVENTS if args.event_id is None or e["id"] == args.event_id]
    if not events:
        print(f"No event matching --event-id='{args.event_id}'. "
              f"Available: {[e['id'] for e in EVENTS]}")
        sys.exit(1)

    print(f"\n{'═'*72}")
    print(f"  AGENT ALPHA — HISTORICAL SIMULATION & ACCURACY BENCHMARK")
    print(f"  Events: {len(events)} | Budget: ${args.budget:.0f} | "
          f"Modes: {[_mode_label(m) for m in sorted_modes]}")
    print(f"  Cache dir: {CACHE_DIR.relative_to(_ROOT)}")
    print(f"  Note: event-conditioned simulation — agents use live news APIs + injected event.")
    print(f"{'═'*72}")

    all_results = []

    for event in events:
        print(f"\n── Event: {event['id']} ──────────────────────────────────────────────")

        # 1. Fetch historical prices
        tickers = [t for t in config.COMPANIES if t not in event.get("exclude_tickers", [])]
        prices = fetch_event_prices(tickers, event["event_date"])
        if not prices or BENCHMARK not in prices:
            print(f"  ERROR: Could not fetch prices for {event['event_date']} — skipping.")
            continue

        # 2. Run / load all modes
        mode_results: dict[int, dict] = {}
        skip_event = False
        for dr in sorted_modes:
            if args.no_pipeline:
                cache = CACHE_DIR / f"{event['id']}_dr{dr}.json"
                if not cache.exists():
                    print(f"  ERROR: --no-pipeline but cache missing for dr={dr}. "
                          f"Run without --no-pipeline first.")
                    skip_event = True
                    break
                with open(cache) as f:
                    mode_results[dr] = json.load(f)
            else:
                mode_results[dr] = load_or_run(event, dr, args.budget, args.force_rerun)

        if skip_event or len(mode_results) != len(sorted_modes):
            continue

        # 3. Print report
        result = print_event_report(event, prices, mode_results)
        all_results.append(result)

    if len(all_results) >= 2:
        print_summary(all_results, sorted_modes)

    if len(all_results) == 0:
        print("\nNo results generated. Check API keys and event dates.")
        sys.exit(1)


if __name__ == "__main__":
    main()
