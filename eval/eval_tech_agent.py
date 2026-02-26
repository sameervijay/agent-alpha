"""
Quick assessment of tech_publications_agent contribution vs the full agent council.
Run with: python eval_tech_agent.py
"""

import time
import sys
from collections import defaultdict

print("=" * 65)
print("  FULL PIPELINE — DETECT PHASE  [langchain backend]")
print("=" * 65)

t0 = time.time()
from agents_langchain.pm_agent import PMAgent
pm = PMAgent()

events = pm.detect_events("")   # empty → full autonomous detection
elapsed = time.time() - t0

# ── Per-agent breakdown ─────────────────────────────────────────
by_agent = defaultdict(list)
for e in events:
    by_agent[e.source_agent].append(e)

print(f"\nTotal events: {len(events)}   ({elapsed:.1f}s)\n")
print(f"  {'Agent':<35} {'Events':>6}  Severities")
print(f"  {'-'*35} {'------':>6}  ----------")
for agent, evts in sorted(by_agent.items(), key=lambda x: -len(x[1])):
    sev = [e.severity[0].upper() for e in evts]
    print(f"  {agent:<35} {len(evts):>6}  {' '.join(sev)}")

# ── Tech publications deep-dive ─────────────────────────────────
tech_events = by_agent.get("tech_publications_agent", [])
print(f"\n── tech_publications_agent events ({len(tech_events)}) {'─'*30}")
for e in tech_events:
    print(f"  [{e.severity.upper():8s}|{e.direction:8s}] {e.headline}")
    print(f"    tickers={e.affected_companies}")
    print(f"    segs   ={e.affected_segments}")
    print(f"    desc   : {e.description[:130]}")
    print()

# ── Uniqueness check ────────────────────────────────────────────
print(f"── Uniqueness check (tech vs all other agents) {'─'*18}")
other_events = [e for e in events if e.source_agent != "tech_publications_agent"]

for te in tech_events:
    th = te.headline.lower()
    overlap = [
        e.headline[:50]
        for e in other_events
        if th[:35] in e.headline.lower() or e.headline.lower()[:35] in th
    ]
    tag = f"OVERLAP -> {overlap}" if overlap else "UNIQUE"
    print(f"  {te.headline[:58]:<58} {tag}")

# ── Severity distribution across agents ────────────────────────
print(f"\n── Severity distribution {'─'*40}")
sev_order = ["critical", "high", "medium", "low"]
for sev in sev_order:
    agents_with_sev = [
        (agent, len([e for e in evts if e.severity == sev]))
        for agent, evts in by_agent.items()
        if any(e.severity == sev for e in evts)
    ]
    if agents_with_sev:
        agents_str = ", ".join(f"{a}({n})" for a, n in agents_with_sev)
        print(f"  {sev.upper():8s}: {agents_str}")

# ── Assessment summary ──────────────────────────────────────────
total = len(events)
tech_n = len(tech_events)
unique_n = sum(
    1 for te in tech_events
    if not any(
        te.headline.lower()[:35] in e.headline.lower() or
        e.headline.lower()[:35] in te.headline.lower()
        for e in other_events
    )
)

print(f"\n── Assessment summary {'─'*43}")
print(f"  tech_publications share : {tech_n}/{total} events ({100*tech_n/total:.0f}%)")
print(f"  unique signals          : {unique_n}/{tech_n} events not covered by other agents")
print(f"  agent wall-clock time   : {elapsed:.1f}s total pipeline")
high_crit = [e for e in tech_events if e.severity in ("high", "critical")]
print(f"  high/critical events    : {len(high_crit)}/{tech_n}")
print()
