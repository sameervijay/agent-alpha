"""Run DeepSeek event with 2 debate rounds and print conviction trajectory."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

EVENT_DESC = (
    "DeepSeek releases R1, a Chinese open-source AI model matching GPT-4 performance "
    "at a fraction of the training compute cost, raising serious questions about whether "
    "AI hyperscalers will reduce GPU orders. NVIDIA stock drops 17% intraday. "
    "Advanced packaging (CoWoS) demand outlook becomes uncertain. "
    "Market debates whether AI training efficiency gains will structurally reduce "
    "datacenter GPU demand for NVIDIA, TSM, and ASML."
)

from langgraph_pipeline import graph

state = {
    "event": EVENT_DESC,
    "lookback_hours": 1,
    "budget": 1000,
    "debate_rounds": 2,
}
out = graph.invoke(state)
result = out.get("result", {})

# Save
out_path = pathlib.Path("data/simulations/deepseek_shock_dr2.json")
out_path.write_text(json.dumps(result, indent=2, default=str))
print(f"\nSaved to {out_path}")

# ── Print conviction trajectory ──────────────────────────────────────────────
ct = result.get("conviction_trajectory", {})

print("\n" + "="*60)
print("CONVICTION TRAJECTORY — DeepSeek Shock")
print("="*60)

print("\nINITIAL (before any debate round):")
print(f"  {'Ticker':<8} {'Conv':>6} {'ST-Conv':>8} {'Rec$':>7}")
print(f"  {'-'*8} {'-'*6} {'-'*8} {'-'*7}")
for ticker, vals in (ct.get("initial") or {}).items():
    print(f"  {ticker:<8} {(vals.get('conviction') or 0):>6.2f} "
          f"{(vals.get('short_term_event_conviction') or 0):>8.2f} "
          f"${(vals.get('recommended_dollars') or 0):>6.0f}")

rounds = ct.get("challenge_rounds") or []
if rounds:
    # Group by round number (_round field or position)
    # The rounds don't have _round field - infer from position
    # Each full round = 5 challengers (one per ticker)
    tickers = ["NVDA", "CDNS", "CRWV", "TSM", "ASML"]
    n_tickers = 5
    for i, ch in enumerate(rounds):
        rn = i // n_tickers + 1
        if i % n_tickers == 0:
            print(f"\nROUND {rn} (post-challenge updates):")
            print(f"  {'Ticker':<8} {'Conv':>6} {'ST-Conv':>8} {'Rec$':>7}  Challenge targets")
            print(f"  {'-'*8} {'-'*6} {'-'*8} {'-'*7}  {'-'*30}")
        ticker = ch.get("challenger", "?")
        uc = ch.get("updated_conviction", "—")
        us = ch.get("updated_short_term_event_conviction", "—")
        ud = ch.get("updated_recommended_dollars", "—")
        targets = ", ".join(
            c.get("target_ticker", "?") for c in (ch.get("challenges") or [])
        )
        print(f"  {ticker:<8} {uc!s:>6} {us!s:>8} ${ud!s:>6}  -> {targets}")

print("\nFINAL ALLOCATION:")
for ticker, dollars in result.get("allocation_dollars", {}).items():
    print(f"  {ticker}: ${dollars:.0f}")
