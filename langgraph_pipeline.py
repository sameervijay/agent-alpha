"""
LangGraph allocation pipeline with PM-led multi-agent coordination.

Flow:
1) PM kicks off domain scouts in parallel (commodities, macro, politics,
   stock market, tech publications), constrained to last-hour changes.
2) PM routes detected changes to affected company analysts.
3) Company analysts produce company briefs and allocation stances.
4) PM facilitates debate and returns a fixed-budget allocation.
"""

from __future__ import annotations

import json
import operator
import re
import time
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import config
from tools import slack_notifier
from agents_langchain.base import clear_session_cache, extract_json, get_final_message
from agents_langchain.commodities_agent import CommoditiesAgent
from agents_langchain.company_analyst_agent import CompanyAnalystAgent
from agents_langchain.macro_agent import MacroAgent
from agents_langchain.pm_agent import PMAgent
from agents_langchain.politics_agent import PoliticsAgent
from agents_langchain.stock_market_agent import StockMarketAgent
from agents_langchain.tech_publications_agent import TechPublicationsAgent
from models.event import Event


COMPANY_TICKERS = list(config.COMPANIES.keys())
DOMAIN_AGENT_NAMES = (
    "commodities_agent",
    "macro_agent",
    "politics_agent",
    "stock_market_agent",
    "tech_publications_agent",
)

# ── Rate-limit retry ───────────────────────────────────────────────────────────
_RETRY_AFTER_RE = re.compile(r'try again in (\d+(?:\.\d+)?)\s*(ms|s)', re.IGNORECASE)


def _parse_retry_after(err_str: str, default: float = 65.0) -> float:
    """Parse the 'retry after X s/ms' hint from an OpenAI 429 error string.

    Returns seconds to wait, with a 10-second safety buffer added on top, and
    a minimum floor of 20 seconds so concurrent sibling agents have a chance to
    finish their own in-flight requests before we retry.
    """
    m = _RETRY_AFTER_RE.search(err_str)
    if not m:
        return default
    value, unit = float(m.group(1)), m.group(2).lower()
    seconds = value / 1000.0 if unit == "ms" else value
    return max(seconds + 10.0, 20.0)


def _invoke_with_rate_retry(fn, label: str, max_retries: int = 3):
    """Call fn(); on 429 rate-limit errors parse Retry-After, sleep, and retry.

    Any non-429 exception is re-raised immediately.
    After exhausting retries the last exception is re-raised so callers can log it.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            err = str(exc)
            if "429" in err:
                wait_s = _parse_retry_after(err)
                print(f"  [rate_limit] {label} — 429, waiting {wait_s:.0f}s "
                      f"(attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait_s)
            else:
                raise
    raise last_exc  # type: ignore[misc]


class PipelineState(TypedDict, total=False):
    # Inputs
    event: str
    lookback_hours: int
    budget: float
    debate_rounds: int  # 0=one-shot, N=N cross-analyst challenge rounds
    no_analysts: bool   # True=skip analyst briefs entirely (PM allocates from events+valuations only)
    # Detection phase (parallel fan-out reducers)
    domain_outputs: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    # Routed company context
    merged_events: list[dict[str, Any]]
    company_event_map: dict[str, list[dict[str, Any]]]
    # Company analysis phase (parallel fan-out reducers)
    company_briefs_raw: Annotated[list[dict[str, Any]], operator.add]
    # PM output
    debate: dict[str, Any]
    allocation_dollars: dict[str, float]
    allocation_pct: dict[str, float]
    result: Optional[dict[str, Any]]
    error: Optional[str]


def _initialize(state: PipelineState) -> PipelineState:
    clear_session_cache()
    from dcf_grounding import clear_engine_cache
    clear_engine_cache()
    event = (state.get("event") or "").strip()
    if not event:
        event = (
            "Run autonomous last-hour change detection across macro, geopolitics, "
            "commodities, market structure, and semiconductor technology updates."
        )
    lookback = int(state.get("lookback_hours") or 1)
    budget = float(state.get("budget") or 1000.0)
    print("\n  [PM] Initializing pipeline: lookback=%sh, budget=$%.0f" % (lookback, budget))
    print("  [PM] Kicking off domain scouts in parallel (commodities, macro, politics, stock_market, tech_publications).\n")
    return {
        "event": event,
        "lookback_hours": lookback,
        "budget": budget,
        "no_analysts": bool(state.get("no_analysts", False)),
    }


def _safe_event_to_dict(event: Any) -> Optional[dict[str, Any]]:
    if isinstance(event, Event):
        return event.to_dict()
    if isinstance(event, dict):
        return event
    return None


def _domain_prompt_context(state: PipelineState) -> str:
    lookback = int(state.get("lookback_hours") or 1)
    user_context = (state.get("event") or "").strip()
    base = (
        f"Focus only on relevant changes from the last {lookback} hour(s). "
        f"For every change, explicitly tag affected companies from: {', '.join(COMPANY_TICKERS)}."
    )
    if user_context:
        return f"{base}\n\nAdditional context from PM:\n{user_context}"
    return base


def _run_domain_detector(agent: Any, agent_name: str, state: PipelineState) -> PipelineState:
    lookback = int(state.get("lookback_hours") or 1)
    print("  [%s] Scanning last %s hour(s) for relevant changes..." % (agent_name, lookback))
    try:
        events = _invoke_with_rate_retry(
            lambda: agent.detect_events(_domain_prompt_context(state)),
            agent_name,
        ) or []
        serialised = [e for e in (_safe_event_to_dict(ev) for ev in events) if e]
        headlines = [e.get("headline", "")[:60] for e in serialised[:5]]
        if serialised:
            print("  [%s] → %d event(s): %s" % (agent_name, len(serialised), "; ".join(headlines) or "(no headline)"))
        else:
            print("  [%s] → 0 events (no material changes in window)" % agent_name)
        return {"domain_outputs": [{"agent": agent_name, "events": serialised}]}
    except Exception as exc:
        print("  [%s] → ERROR: %s" % (agent_name, exc))
        return {
            "domain_outputs": [{"agent": agent_name, "events": []}],
            "errors": [f"{agent_name} failed: {exc}"],
        }


def _detect_commodities(state: PipelineState) -> PipelineState:
    return _run_domain_detector(CommoditiesAgent(), "commodities_agent", state)


def _detect_macro(state: PipelineState) -> PipelineState:
    return _run_domain_detector(MacroAgent(), "macro_agent", state)


def _detect_politics(state: PipelineState) -> PipelineState:
    return _run_domain_detector(PoliticsAgent(), "politics_agent", state)


def _detect_stock_market(state: PipelineState) -> PipelineState:
    return _run_domain_detector(StockMarketAgent(), "stock_market_agent", state)


def _detect_tech_publications(state: PipelineState) -> PipelineState:
    return _run_domain_detector(TechPublicationsAgent(), "tech_publications_agent", state)


def _merge_and_route_events(state: PipelineState) -> PipelineState:
    seen: set[tuple[str, str]] = set()
    merged_events: list[dict[str, Any]] = []
    company_event_map = {ticker: [] for ticker in COMPANY_TICKERS}

    print("  [merge] Deduplicating and routing events to company analysts...")
    for domain_output in state.get("domain_outputs", []):
        agent_name = domain_output.get("agent", "unknown_agent")
        for evt in domain_output.get("events", []):
            evt_dict = dict(evt)
            evt_dict["source_agent"] = evt_dict.get("source_agent", agent_name)
            headline = (evt_dict.get("headline") or "").strip().lower()
            key = (agent_name, headline)
            if not headline or key in seen:
                continue
            seen.add(key)
            merged_events.append(evt_dict)

            affected = [
                t for t in evt_dict.get("affected_companies", [])
                if t in COMPANY_TICKERS
            ]
            for ticker in affected:
                company_event_map[ticker].append(evt_dict)

    routed = " | ".join("%s: %d" % (t, len(company_event_map[t])) for t in COMPANY_TICKERS)
    print("  [merge] → %d unique events; routed by company: %s" % (len(merged_events), routed))

    # Post scout results to Slack: per-agent event headlines + routing
    scout_lines = []
    for domain_output in state.get("domain_outputs", []):
        agent_name = domain_output.get("agent", "?").replace("_agent", "")
        evts = domain_output.get("events", [])
        if evts:
            headlines = "; ".join((e.get("headline") or "")[:55] for e in evts[:3])
            tickers_hit = sorted({t for e in evts for t in e.get("affected_companies", []) if t in COMPANY_TICKERS})
            scout_lines.append(f"• *{agent_name}* ({len(evts)} events → {', '.join(tickers_hit) or 'none'}): _{headlines}_")
        else:
            scout_lines.append(f"• *{agent_name}*: no material changes")
    routing_summary = "  ".join(f"{t}:{len(company_event_map[t])}" for t in COMPANY_TICKERS)
    slack_notifier.post(
        f"*Domain Scouts — {len(merged_events)} unique events routed*\n"
        + "\n".join(scout_lines)
        + f"\n\n`{routing_summary}`"
    )

    return {"merged_events": merged_events, "company_event_map": company_event_map}


def _analyze_company(ticker: str, state: PipelineState) -> PipelineState:
    # ── no_analysts bypass: return empty brief instantly ──
    if state.get("no_analysts", False):
        print("  [analyst_%s] SKIPPED (no_analysts mode)" % ticker)
        return {"company_briefs_raw": [{
            "ticker": ticker,
            "thesis": "",
            "key_drivers": [],
            "key_risks": [],
            "conviction": 0.0,
            "short_term_event_conviction": 0.0,
            "recommended_dollars": 0.0,
            "recommended_weight": 0.0,
            "challenge_to_others": "",
            "proposed_driver_deltas": {},
        }]}

    # Stagger analyst LLM calls to stay under 30k TPM cap (~3-4k tokens each, 5 parallel agents)
    stagger_s = COMPANY_TICKERS.index(ticker) * 15
    if stagger_s:
        time.sleep(stagger_s)

    budget = float(state.get("budget") or 1000.0)
    company_events = state.get("company_event_map", {}).get(ticker, [])
    print("  [analyst_%s] Analyzing %d routed event(s); forming DCF-grounded thesis..." % (ticker, len(company_events)))
    analyst = CompanyAnalystAgent(ticker)

    # ── DCF grounding ──────────────────────────────────────────
    from dcf_grounding import format_dcf_context_for_analyst, get_engine
    dcf_context = format_dcf_context_for_analyst(ticker)
    engine = get_engine(ticker)
    driver_names = list(engine.drivers.keys()) if engine else []
    driver_periods: list[str] = []
    if engine and driver_names:
        first_driver = engine.drivers[driver_names[0]]
        driver_periods = list(first_driver.keys())

    events_block = json.dumps(company_events[:8], indent=2, default=str)

    goal = (
        f"You are the fundamental analyst for {ticker}.\n\n"
        "Review the recent routed events AND the DCF model context below, then produce "
        "a concise, DCF-grounded investment stance for this company.\n\n"
        f"ROUTED_EVENTS:\n{events_block}\n\n"
        f"{dcf_context}\n\n"
    )

    if driver_names:
        goal += (
            "IMPORTANT: Your proposed_driver_deltas must use ONLY these driver names:\n"
            f"  {driver_names}\n"
            f"Valid periods: {driver_periods}\n\n"
        )

    goal += (
        "Return ONLY JSON with keys:\n"
        "  ticker,\n"
        "  thesis (2-4 sentences grounded in the DCF model and events),\n"
        "  key_drivers (list of strings),\n"
        "  key_risks (list of strings),\n"
        "  conviction (0.0-1.0 — long-term fundamental conviction),\n"
        "  short_term_event_conviction (0.0-1.0 — how confident are you this event "
        "creates a near-term price opportunity in the NEXT 2-4 WEEKS, independent of long-term DCF value),\n"
        "  recovery_thesis (1 sentence on expected price direction over next 2-4 weeks given the event),\n"
        f"  recommended_dollars (0-{budget}),\n"
        "  recommended_weight (0.0-1.0),\n"
        "  challenge_to_others (1-2 sentences),\n"
        "  proposed_driver_deltas (dict of driver_name -> {period: delta_value} — "
        "these are ADDITIVE changes to the baseline model drivers, "
        "e.g. {'datacenter_growth': {'FY2028': 0.05}} means +5pp to datacenter growth),\n"
        "  suggested_multiples (dict with exactly 6 keys: "
        "ev_rev_2026, ev_rev_2027, ev_ebitda_2026, ev_ebitda_2027, pe_2026, pe_2027 — "
        "each a float representing the fair forward multiple you believe the market should apply "
        "given current events, growth trajectory, and risk profile; "
        "e.g. {'ev_rev_2026': 12.0, 'ev_rev_2027': 10.5, 'ev_ebitda_2026': 21.0, "
        "'ev_ebitda_2027': 19.0, 'pe_2026': 28.0, 'pe_2027': 26.0}),\n"
        "  rationale_for_deltas (1-2 sentences explaining why you propose these changes).\n"
    )

    try:
        result = _invoke_with_rate_retry(
            lambda: analyst._agent.invoke({"messages": [{"role": "user", "content": goal}]}),
            f"analyst_{ticker}",
        )
        brief = extract_json(get_final_message(result))
        brief["ticker"] = ticker
        conv = brief.get("conviction", 0)
        st_conv = brief.get("short_term_event_conviction", 0)
        rec_d = brief.get("recommended_dollars", 0)
        thesis_preview = (brief.get("thesis") or "")[:80]
        recovery = (brief.get("recovery_thesis") or "")[:100]
        print("  [analyst_%s] → conviction=%.2f, st_event_conv=%.2f, recommended=$%.0f | %s" % (
            ticker, conv, st_conv, rec_d,
            thesis_preview + ("..." if len(brief.get("thesis") or "") > 80 else ""),
        ))
        slack_notifier.post(
            f"*[Analyst: {ticker}]* conviction={conv:.0%}, event_conv={st_conv:.0%}, recommended=${rec_d:.0f}\n"
            f"_{brief.get('thesis', '')[:200]}_\n"
            f"Near-term: _{recovery}_"
        )
        return {"company_briefs_raw": [brief]}
    except Exception as exc:
        print("  [analyst_%s] → ERROR: %s" % (ticker, exc))
        return {
            "company_briefs_raw": [{
                "ticker": ticker,
                "thesis": f"Analyst error for {ticker}",
                "key_drivers": [],
                "key_risks": [str(exc)],
                "conviction": 0.0,
                "recommended_dollars": 0.0,
                "recommended_weight": 0.0,
                "challenge_to_others": "",
                "proposed_driver_deltas": {},
            }],
            "errors": [f"analyst_{ticker.lower()} failed: {exc}"],
        }


def _analyze_nvda(state: PipelineState) -> PipelineState:
    return _analyze_company("NVDA", state)


def _analyze_cdns(state: PipelineState) -> PipelineState:
    return _analyze_company("CDNS", state)


def _analyze_crwv(state: PipelineState) -> PipelineState:
    return _analyze_company("CRWV", state)


def _analyze_tsm(state: PipelineState) -> PipelineState:
    return _analyze_company("TSM", state)


def _analyze_asml(state: PipelineState) -> PipelineState:
    return _analyze_company("ASML", state)


# Map of names an analyst can use when requesting scout intel
_SCOUT_AGENT_MAP = {
    "commodities": CommoditiesAgent,
    "commodities_agent": CommoditiesAgent,
    "macro": MacroAgent,
    "macro_agent": MacroAgent,
    "politics": PoliticsAgent,
    "politics_agent": PoliticsAgent,
    "stock_market": StockMarketAgent,
    "stock_market_agent": StockMarketAgent,
    "tech_publications": TechPublicationsAgent,
    "tech_publications_agent": TechPublicationsAgent,
    "tech": TechPublicationsAgent,
}


def _execute_info_requests(
    info_requests: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Execute analyst intel requests against live domain scouts.

    Args:
        info_requests: list of {requester, domain_agent, question}

    Returns:
        {requester_ticker: [formatted_response_strings]}
    """
    responses: dict[str, list[str]] = {}
    for req in info_requests:
        requester = req.get("requester", "?")
        domain = (req.get("domain_agent") or "").lower().strip()
        question = (req.get("question") or "").strip()
        if not domain or not question:
            continue
        agent_cls = _SCOUT_AGENT_MAP.get(domain)
        if not agent_cls:
            print(f"  [intel_req] Unknown domain '{domain}' requested by {requester} — skipping")
            continue
        print(f"  [intel_req] {requester} → {domain}: {question[:80]}...")
        slack_notifier.post(f"_:mag: {requester} requests intel from *{domain}*: {question[:200]}_")
        try:
            agent = agent_cls()
            events = _invoke_with_rate_retry(
                lambda: agent.detect_events(question),
                f"intel_{domain}",
            ) or []
            if events:
                lines = []
                for ev in events[:4]:
                    d = ev.to_dict() if hasattr(ev, "to_dict") else (ev if isinstance(ev, dict) else {})
                    lines.append(f"  • {d.get('headline', str(ev))[:120]}")
                intel_text = f"[{domain}] {len(events)} finding(s):\n" + "\n".join(lines)
            else:
                intel_text = f"[{domain}] No new findings for: {question[:100]}"
            responses.setdefault(requester, []).append(intel_text)
            slack_notifier.post(f"*Scout response to {requester} ({domain}):*\n```\n{intel_text[:600]}\n```")
        except Exception as exc:
            print(f"  [intel_req] {domain} failed: {exc}")
    return responses


def _run_challenge_round(
    round_num: int,
    briefs: list[dict[str, Any]],
    prior_challenges: list[dict[str, Any]],
    budget: float,
    scout_intel: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Two-pass debate round: challenge pass then forced response pass.

    Pass 1 — each analyst generates outgoing challenges to peers.
    Pass 2 — each analyst sees ONLY the challenges directed at them and must
              respond directly: either update conviction by ≥5pp or provide a
              specific quantitative rebuttal. No vague "I disagree."

    Returns:
        (challenges + responses, raw_info_requests)
    """
    challenges: list[dict[str, Any]] = []
    raw_info_requests: list[dict[str, Any]] = []

    # ── Pass 1: outgoing challenges ──────────────────────────────────────────
    for brief in briefs:
        ticker = brief.get("ticker", "?")
        other_briefs = [b for b in briefs if b.get("ticker") != ticker]
        prior_to_me = [c for c in prior_challenges if any(
            ch.get("target_ticker") == ticker for ch in c.get("challenges", [])
        )]

        goal = (
            f"You are the {ticker} analyst. This is debate round {round_num}, challenge pass.\n\n"
            f"YOUR CURRENT POSITION:\n{json.dumps(brief, indent=2, default=str)}\n\n"
            f"OTHER ANALYSTS' POSITIONS:\n{json.dumps(other_briefs, indent=2, default=str)}\n\n"
        )
        if prior_to_me:
            goal += f"CHALLENGES DIRECTED AT YOU IN PRIOR ROUNDS:\n{json.dumps(prior_to_me, indent=2, default=str)}\n\n"
        if scout_intel and scout_intel.get(ticker):
            intel_block = "\n".join(scout_intel[ticker])
            goal += f"ADDITIONAL INTELLIGENCE (from your prior-round scout requests):\n{intel_block}\n\n"

        # Position floor: prevent zeroing out any name with meaningful event conviction
        floor_note = (
            "POSITION FLOOR RULE: Do not recommend $0 for any company whose "
            "short_term_event_conviction > 0.5 — even fundamentally challenged names deserve "
            "a small position when they have near-term event momentum.\n"
        )
        goal += (
            "Task: Challenge the analyst(s) whose thesis you most disagree with. "
            "Reference specific claims. For each analyst you challenge, you MUST also state ONE "
            "reason their near-term bull case might be correct (steel-man).\n"
            f"{floor_note}"
            "If you need specific data to strengthen or refute a claim, request it from a domain scout.\n\n"
            "Return ONLY JSON with:\n"
            "  challenger (your ticker string),\n"
            "  challenges (list of {target_ticker, point_of_contention, your_counter_evidence, "
            "steel_man: one sentence on why their near-term bull case might still be right}),\n"
            "  updated_conviction (0.0-1.0),\n"
            "  updated_short_term_event_conviction (0.0-1.0 — revised near-term view after this round),\n"
            f"  updated_recommended_dollars (0-{budget:.0f}),\n"
            "  updated_thesis (1-2 sentences),\n"
            "  information_requests (list of {domain_agent: one of [commodities, macro, politics, "
            "stock_market, tech_publications], question: specific data question} — "
            "optional, max 2, only if truly needed to resolve a disagreement)."
        )
        try:
            analyst = CompanyAnalystAgent(ticker)
            result = _invoke_with_rate_retry(
                lambda: analyst._agent.invoke({"messages": [{"role": "user", "content": goal}]}),
                f"debate_r{round_num}_{ticker}",
            )
            challenge = extract_json(get_final_message(result))
            challenge["challenger"] = ticker
            challenges.append(challenge)
            for ch in (challenge.get("challenges") or [])[:2]:
                target = ch.get("target_ticker", "?")
                evidence = (ch.get("your_counter_evidence") or ch.get("point_of_contention") or "")[:200]
                print(f"  [debate_r{round_num}] {ticker} → {target}: {evidence[:80]}...")
                slack_notifier.post(
                    f"*Round {round_num} — {ticker} challenges {target}:*\n_{evidence}_"
                )
            for req in (challenge.get("information_requests") or [])[:2]:
                req["requester"] = ticker
                raw_info_requests.append(req)
        except Exception as exc:
            print(f"  [debate_r{round_num}] {ticker} failed: {exc}")

    # ── Pass 2: forced direct responses to incoming challenges ───────────────
    # Build a map of which challenges are directed at each ticker
    incoming: dict[str, list[dict]] = {}
    for ch_block in challenges:
        challenger = ch_block.get("challenger", "")
        for ch in (ch_block.get("challenges") or []):
            target = ch.get("target_ticker", "")
            if target:
                incoming.setdefault(target, []).append({
                    "from": challenger,
                    "point": ch.get("point_of_contention", ""),
                    "evidence": ch.get("your_counter_evidence", ""),
                })

    responses: list[dict[str, Any]] = []
    for brief in briefs:
        ticker = brief.get("ticker", "?")
        directed_at_me = incoming.get(ticker, [])
        if not directed_at_me:
            continue  # no challenges to respond to this round

        n_challenges = len(directed_at_me)
        goal = (
            f"You are the {ticker} analyst. This is the RESPONSE PASS of debate round {round_num}.\n\n"
            f"YOUR CURRENT POSITION:\n{json.dumps(brief, indent=2, default=str)}\n\n"
            f"{n_challenges} analyst(s) have directly challenged your thesis:\n"
            f"{json.dumps(directed_at_me, indent=2)}\n\n"
            "Task: Respond to EACH challenge individually.\n"
            "  - If you find a challenge ≥50% compelling: state exactly what convinced you "
            "and update your conviction by AT LEAST 5pp in the appropriate direction.\n"
            "  - If you reject a challenge: provide ONE specific quantitative counterargument "
            "(a number, a ratio, a consensus estimate) — not a vague 'I disagree'.\n"
            f"  - If {n_challenges} or more challenges target you and you reject ALL of them, "
            "you MUST state the single data point that would change your mind.\n"
            "ALSO: Consider whether the market reaction to this event is overdone. "
            "High-quality semis frequently rebound 10-20% within 4 weeks of a panic selloff. "
            "If you believe a name has been oversold, increase its st_event_conviction.\n\n"
            "Return ONLY JSON with:\n"
            "  responder (your ticker),\n"
            "  challenge_responses (list of {challenge_from, agreed: bool, "
            "reasoning, conviction_delta: float}),\n"
            "  response_conviction (0.0-1.0 — conviction AFTER processing challenges),\n"
            "  response_st_event_conviction (0.0-1.0),\n"
            f"  response_recommended_dollars (0-{budget:.0f}),\n"
            "  what_would_change_my_mind (1 sentence — the specific data that would shift you)."
        )
        try:
            analyst = CompanyAnalystAgent(ticker)
            result = _invoke_with_rate_retry(
                lambda: analyst._agent.invoke({"messages": [{"role": "user", "content": goal}]}),
                f"resp_r{round_num}_{ticker}",
            )
            resp = extract_json(get_final_message(result))
            resp["responder"] = ticker
            resp["_pass"] = "response"
            responses.append(resp)

            old_conv = brief.get("conviction", 0)
            new_conv = resp.get("response_conviction", old_conv)
            delta = round(new_conv - old_conv, 2)
            print(f"  [resp_r{round_num}] {ticker}: conviction {old_conv:.2f} → {new_conv:.2f} "
                  f"({delta:+.2f}) | {resp.get('what_would_change_my_mind', '')[:60]}")
            slack_notifier.post(
                f"*Response pass R{round_num} — {ticker}:* "
                f"conviction {old_conv:.0%} → {new_conv:.0%} ({delta:+.0%})\n"
                f"_To change my mind: {resp.get('what_would_change_my_mind', '')[:200]}_"
            )

            # Apply response updates to the live brief immediately so later
            # responders in this same pass see the updated state
            brief["conviction"] = new_conv
            brief["short_term_event_conviction"] = resp.get(
                "response_st_event_conviction", brief.get("short_term_event_conviction", 0)
            )
            brief["recommended_dollars"] = resp.get(
                "response_recommended_dollars", brief.get("recommended_dollars", 0)
            )
        except Exception as exc:
            print(f"  [resp_r{round_num}] {ticker} response failed: {exc}")

    return challenges + responses, raw_info_requests


def _normalise_allocations(raw_alloc: dict[str, Any], budget: float) -> dict[str, float]:
    alloc = {ticker: float(raw_alloc.get(ticker, 0.0) or 0.0) for ticker in COMPANY_TICKERS}
    total = sum(alloc.values())
    if total <= 0:
        equal = round(budget / len(COMPANY_TICKERS), 2)
        fallback = {t: equal for t in COMPANY_TICKERS}
        # rounding guard for exact budget match
        diff = round(budget - sum(fallback.values()), 2)
        fallback[COMPANY_TICKERS[0]] = round(fallback[COMPANY_TICKERS[0]] + diff, 2)
        return fallback

    scaled = {t: round(v * budget / total, 2) for t, v in alloc.items()}
    diff = round(budget - sum(scaled.values()), 2)
    largest = max(scaled, key=scaled.get)
    scaled[largest] = round(scaled[largest] + diff, 2)
    return scaled


def _compute_analyst_disagreement(briefs: list[dict[str, Any]]) -> float:
    """Mean absolute deviation of short_term_event_conviction across analyst briefs.

    Returns a value in [0, 0.5]: 0 = perfect consensus, ~0.5 = maximum spread.
    Only includes briefs that have a valid ticker and conviction score.
    """
    vals = [
        float(b.get("short_term_event_conviction", 0.5))
        for b in briefs
        if b.get("ticker") and b.get("short_term_event_conviction") is not None
    ]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return sum(abs(v - mean) for v in vals) / len(vals)


def _pm_debate_and_allocate(state: PipelineState) -> PipelineState:
    budget = float(state.get("budget") or 1000.0)
    briefs = state.get("company_briefs_raw", [])
    merged_events = state.get("merged_events", [])

    if not briefs:
        return {"error": "No company briefs generated.", "allocation_dollars": {}}

    print("  [PM] Facilitating cross-company debate and allocating $%.0f..." % budget)

    # ── DCF valuations from analyst-proposed deltas ─────────────
    from dcf_grounding import compute_baseline, apply_deltas_and_compute

    dcf_results: dict[str, dict] = {}
    for brief in briefs:
        ticker = brief.get("ticker", "")
        deltas = brief.get("proposed_driver_deltas", {})

        if deltas:
            dcf_result = apply_deltas_and_compute(ticker, deltas)
        else:
            baseline = compute_baseline(ticker)
            dcf_result = {
                'baseline_price': baseline['implied_price'],
                'adjusted_price': baseline['implied_price'],
                'current_price': baseline['current_price'],
                'upside': baseline['upside'],
                'alpha_vs_baseline': 0.0,
            } if baseline else None

        if dcf_result:
            dcf_results[ticker] = dcf_result
            print("  [PM] DCF %s: baseline=$%.2f, adjusted=$%.2f, upside=%.1f%%, alpha=$%.2f" % (
                ticker,
                dcf_result.get('baseline_price', 0),
                dcf_result.get('adjusted_price', 0),
                dcf_result.get('upside', 0) * 100,
                dcf_result.get('alpha_vs_baseline', 0),
            ))

    dcf_summary_lines = []
    for ticker, dr in dcf_results.items():
        dcf_summary_lines.append(
            f"  {ticker}: baseline=${dr.get('baseline_price',0):.2f}, "
            f"analyst-adjusted=${dr.get('adjusted_price',0):.2f}, "
            f"market=${dr.get('current_price',0):.2f}, "
            f"upside={dr.get('upside',0):+.1%}, "
            f"alpha_vs_baseline=${dr.get('alpha_vs_baseline',0):+.2f}"
        )
    dcf_block = "\n".join(dcf_summary_lines) if dcf_summary_lines else "(no DCF models available)"

    if dcf_summary_lines:
        slack_notifier.post("*DCF Valuations (analyst-adjusted):*\n```\n" + "\n".join(
            f"{t}: adj=${dr.get('adjusted_price', 0):.2f}  mkt=${dr.get('current_price', 0):.2f}  "
            f"upside={dr.get('upside', 0):+.1%}"
            for t, dr in dcf_results.items()
        ) + "\n```")

    pm = PMAgent()

    # ── Optional multi-round cross-analyst debate ────────────────
    debate_rounds = int(state.get("debate_rounds") or 0)
    all_challenges: list[dict[str, Any]] = []
    pm_probe: str = ""
    probe_responses: list[dict[str, Any]] = []
    debate_gated = False  # True when debate was skipped due to analyst consensus

    if debate_rounds > 0:
        disagreement = _compute_analyst_disagreement(briefs)
        threshold = config.DEBATE_DISAGREEMENT_THRESHOLD
        conviction_vals = [
            f"{b.get('ticker','?')}={b.get('short_term_event_conviction', 0):.2f}"
            for b in briefs if b.get("ticker")
        ]
        print(f"  [PM] Analyst disagreement MAD={disagreement:.3f} (threshold={threshold}) "
              f"| {', '.join(conviction_vals)}")

        if disagreement < threshold:
            debate_gated = True
            print(f"  [PM] Debate GATED — analysts broadly agree (MAD={disagreement:.3f} < {threshold}). "
                  f"Skipping {debate_rounds} challenge round(s).")
            slack_notifier.post(
                f"_Debate gated: analysts broadly agree (disagreement={disagreement:.2f} < {threshold:.2f}). "
                f"Skipping {debate_rounds} challenge round(s)._"
            )
        else:
            print(f"  [PM] Debate PROCEEDING — genuine disagreement detected (MAD={disagreement:.3f} ≥ {threshold}).")
            slack_notifier.post(
                f"*Cross-Analyst Debate — {debate_rounds} challenge round(s) starting*\n"
                f"_{len(briefs)} analysts will challenge each other's theses "
                f"(disagreement={disagreement:.2f})_"
            )

        if not debate_gated:
            scout_intel: dict[str, list[str]] = {}
            for rn in range(1, debate_rounds + 1):
                print("  [PM] Running analyst challenge round %d/%d..." % (rn, debate_rounds))
                slack_notifier.post(f"*── Challenge Round {rn}/{debate_rounds} ──*")
                round_challenges, info_requests = _run_challenge_round(
                    rn, briefs, all_challenges, budget, scout_intel
                )
                all_challenges.extend(round_challenges)
                # Execute any scout intel requests and feed results into next round
                if info_requests:
                    print("  [PM] Executing %d scout intel request(s)..." % len(info_requests))
                    scout_intel = _execute_info_requests(info_requests)

            # ── Merge final challenge-round positions back into briefs ──────────────
            # The PM sees the original analyst briefs; after N rounds analysts may have
            # revised their conviction and recommended_dollars. Apply those updates so
            # the PM synthesizes against the most current analyst stances, not stale ones.
            # Prefer response-pass values (response_*) over challenge-pass values (updated_*)
            # since response pass is later and reflects absorbed challenges
            latest_challenge: dict[str, dict] = {}
            latest_response: dict[str, dict] = {}
            for ch in all_challenges:
                if ch.get("_pass") == "response":
                    t = ch.get("responder", "")
                    if t:
                        latest_response[t] = ch
                else:
                    t = ch.get("challenger", "")
                    if t:
                        latest_challenge[t] = ch

            updated_count = 0
            for brief in briefs:
                t = brief.get("ticker", "")
                resp = latest_response.get(t)
                ch = latest_challenge.get(t)
                if resp:
                    # Response-pass values take priority — they reflect direct challenge engagement
                    if "response_conviction" in resp:
                        brief["conviction"] = resp["response_conviction"]
                    if "response_st_event_conviction" in resp:
                        brief["short_term_event_conviction"] = resp["response_st_event_conviction"]
                    if "response_recommended_dollars" in resp:
                        brief["recommended_dollars"] = resp["response_recommended_dollars"]
                    updated_count += 1
                elif ch:
                    if "updated_conviction" in ch:
                        brief["conviction"] = ch["updated_conviction"]
                    if "updated_short_term_event_conviction" in ch:
                        brief["short_term_event_conviction"] = ch["updated_short_term_event_conviction"]
                    if "updated_recommended_dollars" in ch:
                        brief["recommended_dollars"] = ch["updated_recommended_dollars"]
                    if "updated_thesis" in ch:
                        brief["thesis"] = ch["updated_thesis"]
                    updated_count += 1
            if updated_count:
                print(f"  [PM] Applied post-debate position updates for {updated_count} analyst(s).")

            # PM probing question: target mean-reversion and the most-challenged name
            print("  [PM] Formulating probing question...")
            most_challenged = {}
            for ch_block in all_challenges:
                for ch in (ch_block.get("challenges") or []):
                    t = ch.get("target_ticker", "")
                    if t:
                        most_challenged[t] = most_challenged.get(t, 0) + 1
            top_challenged = max(most_challenged, key=most_challenged.get) if most_challenged else "NVDA"
            pm_probe = pm._pm_invoke(
                f"The most-challenged company in this debate is {top_challenged} "
                f"({most_challenged.get(top_challenged, 0)} challenges directed at it).\n\n"
                "Ask ONE sharp contrarian probing question about whether the market reaction to "
                f"this event is OVERDONE for {top_challenged}. High-quality semis frequently "
                "rebound 10-20% within 4 weeks of a panic selloff — force analysts to explicitly "
                "price the mean-reversion probability.\n\n"
                f"ANALYST_BRIEFS:\n{json.dumps(briefs, indent=2, default=str)}\n\n"
                f"CHALLENGE_TRANSCRIPT:\n{json.dumps(all_challenges, indent=2, default=str)}\n\n"
                "Return JSON with key 'question'."
            ).get("question", "")
            if pm_probe:
                print("  [PM probe] %s" % pm_probe[:100])
                slack_notifier.post(f"_PM probe: {pm_probe[:400]}_")

            # ── Analysts answer the PM probe ─────────────────────────────────────
            # Each analyst gets one chance to respond directly to the PM's sharpest
            # question, allowing the PM to weight final allocation against those answers.
            if pm_probe:
                print("  [PM] Collecting analyst probe responses...")
                slack_notifier.post("*Analysts respond to PM probe:*")
                for i, brief in enumerate(briefs):
                    t = brief.get("ticker", "?")
                    if i > 0:
                        time.sleep(12)  # stagger to avoid TPM spike
                    response_goal = (
                        f"You are the {t} analyst. The PM has asked the following sharp question:\n\n"
                        f"QUESTION: {pm_probe}\n\n"
                        f"YOUR CURRENT POSITION:\n{json.dumps(brief, indent=2, default=str)}\n\n"
                        "Answer directly and concisely, citing specific data from your DCF model or "
                        "the events you analyzed. Do NOT deflect — take a clear stance.\n\n"
                        "Return ONLY JSON with keys:\n"
                        "  ticker (string),\n"
                        "  probe_response (2-4 sentences answering the question),\n"
                        "  position_change ('strengthen' | 'weaken' | 'neutral' — did this probe shift your view?)."
                    )
                    try:
                        analyst = CompanyAnalystAgent(t)
                        result = _invoke_with_rate_retry(
                            lambda: analyst._agent.invoke(
                                {"messages": [{"role": "user", "content": response_goal}]}
                            ),
                            f"probe_resp_{t}",
                        )
                        resp = extract_json(get_final_message(result))
                        resp["ticker"] = t
                        probe_responses.append(resp)
                        resp_text = (resp.get("probe_response") or "")[:150]
                        pos_change = resp.get("position_change", "neutral")
                        print(f"  [probe_resp_{t}] [{pos_change}] {resp_text}...")
                        slack_notifier.post(
                            f"• *{t}* [{pos_change}]: _{resp_text}_"
                        )
                    except Exception as exc:
                        print(f"  [probe_resp_{t}] failed: {exc}")

    # Detect no_analysts mode (all briefs have zero conviction)
    is_no_analysts = all(float(b.get("conviction", 0)) == 0 for b in briefs)

    debate_goal = (
        "You are the PM facilitating final capital allocation.\n\n"
        f"FIXED_BUDGET_DOLLARS: {budget}\n"
        f"COVERED_COMPANIES: {', '.join(COMPANY_TICKERS)}\n\n"
        f"RECENT_DOMAIN_EVENTS:\n{json.dumps(merged_events[:15], indent=2, default=str)}\n\n"
    )
    if is_no_analysts:
        debate_goal += (
            "NOTE: No analyst input available for this allocation. "
            "You must allocate based SOLELY on domain events and DCF/multiples valuations below.\n\n"
        )
    else:
        debate_goal += (
            f"COMPANY_ANALYST_BRIEFS:\n{json.dumps(briefs, indent=2, default=str)}\n\n"
        )
    debate_goal += f"DCF VALUATIONS (analyst-adjusted):\n{dcf_block}\n\n"
    if all_challenges:
        debate_goal += (
            f"DEBATE_TRANSCRIPT ({len(all_challenges)} challenges across "
            f"{debate_rounds} round(s)):\n{json.dumps(all_challenges, indent=2, default=str)}\n\n"
        )
    if pm_probe:
        debate_goal += f"PM_PROBING_QUESTION: {pm_probe}\n\n"
    if probe_responses:
        debate_goal += (
            f"ANALYST_PROBE_RESPONSES ({len(probe_responses)} analysts answered):\n"
            f"{json.dumps(probe_responses, indent=2, default=str)}\n\n"
        )
    if is_no_analysts:
        debate_goal += (
            "Task (NO ANALYST INPUT — allocate from events + valuations only):\n"
            "1) Analyze domain events and identify which companies are most affected.\n"
            "2) Use DCF/multiples valuations to assess relative value.\n"
            "3) Allocate the FULL fixed budget across companies. "
            "Favor CONCENTRATION in the 1-2 names most impacted by events with favorable valuations. "
            "Do NOT spread evenly.\n"
            "4) Provide rationale grounded in events and valuations.\n\n"
        )
    else:
        debate_goal += (
            "Task:\n"
            "1) Summarize key agreements/disagreements across analysts.\n"
            "2) Identify the companies with the highest short_term_event_conviction — "
            "these are your primary allocation targets for this event-driven portfolio.\n"
            "3) Weight allocation primarily by short_term_event_conviction × conviction. "
            "Favor CONCENTRATION in the top 1-2 names with the strongest event-driven signal; "
            "do NOT spread evenly just to diversify — event-driven portfolios should be decisive. "
            "Use DCF upside only as a secondary risk filter: if a company has deeply negative DCF upside "
            "(<-30%) AND low event conviction, trim modestly, but never zero out based on valuation alone.\n"
            "4) Allocate the FULL fixed budget across companies.\n\n"
        )
    debate_goal += (
        "Return ONLY JSON with keys:\n"
        "  debate_summary (string),\n"
        "  rationale (string referencing event conviction and DCF risk-filter applied),\n"
        "  risk_notes (list of strings),\n"
        "  event_conviction_rankings (list of {ticker, short_term_event_conviction, conviction, rationale}),\n"
        "  allocation_dollars (dict ticker->float) including all covered companies."
    )

    try:
        debate_result = pm._pm_invoke(debate_goal)
        raw_alloc = debate_result.get("allocation_dollars", {})
        alloc_dollars = _normalise_allocations(raw_alloc, budget)
        alloc_pct = {t: round(v / budget, 4) for t, v in alloc_dollars.items()} if budget > 0 else {
            t: 0.0 for t in COMPANY_TICKERS
        }
        debate_result['dcf_valuations'] = dcf_results
        debate_result['debate_rounds_run'] = debate_rounds
        debate_result['debate_gated'] = debate_gated
        debate_result['challenge_transcript'] = all_challenges
        debate_result['pre_debate_briefs'] = briefs  # for benchmark comparison
        summary = (debate_result.get("debate_summary") or "")[:120]
        print("  [PM] → allocation done. Debate summary: %s" % (summary + "..." if len(debate_result.get("debate_summary") or "") > 120 else summary))

        # Post PM debate summary
        slack_notifier.post(
            f"*PM Debate Summary:*\n_{(debate_result.get('debate_summary') or '')[:400]}_\n\n"
            f"*Rationale:* {(debate_result.get('rationale') or '')[:300]}"
        )

        # Post final allocation
        alloc_lines = "\n".join(
            f"  {t}: ${v:.0f} ({v / budget:.0%})" for t, v in alloc_dollars.items()
        )
        slack_notifier.post(f"*Final Allocation (budget=${budget:.0f}):*\n```\n{alloc_lines}\n```")

        return {
            "debate": debate_result,
            "allocation_dollars": alloc_dollars,
            "allocation_pct": alloc_pct,
            "error": None,
        }
    except Exception as exc:
        print("  [PM] → ERROR: %s" % exc)
        return {"error": f"PM debate/allocation failed: {exc}", "allocation_dollars": {}}


def _finalize(state: PipelineState) -> PipelineState:
    budget = float(state.get("budget") or 1000.0)
    allocation = state.get("allocation_dollars", {})
    debate = state.get("debate", {})
    debate_rounds_run = int(debate.get("debate_rounds_run") or 0)
    print("  [finalize] Pipeline complete. Total allocated: $%.2f" % sum(allocation.values()))

    # ── Benchmark: pre-debate vs post-debate allocation comparison ──
    briefs = debate.get("pre_debate_briefs", state.get("company_briefs_raw", []))
    dcf_vals = debate.get("dcf_valuations", {})

    # Pre-debate allocation = analyst recommended_dollars, normalized to budget
    pre_raw = {b.get("ticker", ""): float(b.get("recommended_dollars") or 0) for b in briefs}
    pre_total = sum(pre_raw.values())
    pre_alloc = (
        {t: round(v * budget / pre_total, 2) for t, v in pre_raw.items()}
        if pre_total > 0 else {t: round(budget / len(COMPANY_TICKERS), 2) for t in COMPANY_TICKERS}
    )

    def _score(alloc: dict[str, float], briefs_: list[dict], dcf_: dict[str, dict]) -> float:
        """Conviction-weighted DCF-upside score: sum(weight * conviction * max(upside, 0))."""
        conv_map = {b.get("ticker", ""): float(b.get("conviction") or 0) for b in briefs_}
        total = sum(alloc.values()) or 1.0
        score = 0.0
        for t, dollars in alloc.items():
            weight = dollars / total
            conviction = conv_map.get(t, 0.0)
            upside = max(0.0, dcf_.get(t, {}).get("upside", 0.0))
            score += weight * conviction * upside
        return round(score, 6)

    pre_score = _score(pre_alloc, briefs, dcf_vals)
    post_score = _score(allocation, briefs, dcf_vals)
    score_delta = round(post_score - pre_score, 6)

    # Print benchmark table
    print("\n  ── DEBATE BENCHMARK (%s) ──" % (
        f"{debate_rounds_run}-round debate" if debate_rounds_run > 0 else "one-shot"
    ))
    print("  %-6s  %10s  %10s  %10s" % ("Ticker", "Pre-debate", "Post-debate", "Shift"))
    for t in COMPANY_TICKERS:
        pre_d = pre_alloc.get(t, 0)
        post_d = allocation.get(t, 0)
        shift = post_d - pre_d
        print("  %-6s  %10.2f  %10.2f  %+10.2f" % (t, pre_d, post_d, shift))
    print("  Conv×Upside score — pre: %.4f  post: %.4f  delta: %+.4f" % (
        pre_score, post_score, score_delta
    ))

    # Post benchmark to Slack
    bench_lines = "\n".join(
        f"  {t}: pre=${pre_alloc.get(t, 0):.0f} → post=${allocation.get(t, 0):.0f}"
        f"  ({allocation.get(t, 0) - pre_alloc.get(t, 0):+.0f})"
        for t in COMPANY_TICKERS
    )
    slack_notifier.post(
        f"*Benchmark ({debate_rounds_run}-round debate vs analyst pre-debate):*\n"
        f"```\n{bench_lines}\n```\n"
        f"Conv×Upside score: {pre_score:.4f} → {post_score:.4f}  ({score_delta:+.4f})"
    )

    # Build conviction trajectory from initial briefs + challenge transcript
    initial_convictions = {
        b.get("ticker", ""): {
            "conviction": b.get("conviction"),
            "short_term_event_conviction": b.get("short_term_event_conviction"),
            "recommended_dollars": b.get("recommended_dollars"),
        }
        for b in briefs
    }
    challenge_transcript = debate.get("challenge_transcript", [])

    result = {
        "budget": budget,
        "lookback_hours": int(state.get("lookback_hours") or 1),
        "domain_agents": list(DOMAIN_AGENT_NAMES),
        "events_detected": len(state.get("merged_events", [])),
        "routed_events_by_company": {
            t: len(v) for t, v in state.get("company_event_map", {}).items()
        },
        "allocation_dollars": allocation,
        "allocation_pct": state.get("allocation_pct", {}),
        "debate_summary": debate.get("debate_summary", ""),
        "rationale": debate.get("rationale", ""),
        "risk_notes": debate.get("risk_notes", []),
        "dcf_valuations": dcf_vals,
        "no_analysts": bool(state.get("no_analysts", False)),
        "benchmark": {
            "debate_rounds": debate_rounds_run,
            "no_analysts": bool(state.get("no_analysts", False)),
            "debate_gated": debate.get("debate_gated", False),
            "analyst_disagreement_mad": round(_compute_analyst_disagreement(briefs), 4),
            "pre_debate_allocation": pre_alloc,
            "post_debate_allocation": allocation,
            "pre_score": pre_score,
            "post_score": post_score,
            "score_delta": score_delta,
        },
        "conviction_trajectory": {
            "initial": initial_convictions,
            "challenge_rounds": challenge_transcript,
        },
        "errors": state.get("errors", []),
    }

    # ── Persist analyst views to data/analyst_views/{TICKER}_view.json ──
    _persist_analyst_views(briefs, dcf_vals)

    return {"result": result, "error": state.get("error")}


def _persist_analyst_views(briefs: list[dict], dcf_vals: dict[str, dict]) -> None:
    """Write/update analyst view JSONs with latest brief data, financials, and multiples."""
    from datetime import datetime
    from pathlib import Path
    from dcf_grounding import compute_financials

    views_dir = Path(config.ANALYST_VIEWS_DIR)
    views_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()

    for brief in briefs:
        ticker = brief.get("ticker", "")
        if not ticker:
            continue

        view_path = views_dir / f"{ticker}_view.json"

        # Load existing view if present
        existing = {}
        if view_path.exists():
            try:
                existing = json.loads(view_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Merge: keep established_at from existing, update everything else
        established = existing.get("established_at", now)

        # ── Model financials from DCF engine ──
        financials = compute_financials(ticker)
        model_fin = {}
        if financials:
            model_fin = {
                "rev_2026": financials["rev_2026"],
                "rev_2027": financials["rev_2027"],
                "ebitda_2026": financials["ebitda_2026"],
                "ebitda_2027": financials["ebitda_2027"],
                "eps_2026": financials["eps_2026"],
                "eps_2027": financials["eps_2027"],
            }

        # ── Suggested multiples from analyst brief ──
        suggested = brief.get("suggested_multiples", existing.get("suggested_multiples", {}))

        # ── Compute multiples-implied prices ──
        implied_prices = {}
        if financials and suggested:
            shares = financials.get("shares", 0)
            net_debt = financials.get("net_debt", 0)
            if shares > 0:
                # EV-based: implied_price = (metric × multiple - net_debt) / shares
                for key, metric_key in [
                    ("ev_rev_2026", "rev_2026"),
                    ("ev_rev_2027", "rev_2027"),
                    ("ev_ebitda_2026", "ebitda_2026"),
                    ("ev_ebitda_2027", "ebitda_2027"),
                ]:
                    mult = suggested.get(key)
                    metric = financials.get(metric_key, 0)
                    if mult and metric:
                        implied_tev = metric * mult
                        implied_prices[key] = round((implied_tev - net_debt) / shares, 2)

                # P/E-based: implied_price = EPS × multiple
                for key, eps_key in [
                    ("pe_2026", "eps_2026"),
                    ("pe_2027", "eps_2027"),
                ]:
                    mult = suggested.get(key)
                    eps_val = financials.get(eps_key, 0)
                    if mult and eps_val:
                        implied_prices[key] = round(eps_val * mult, 2)

        view = {
            "ticker": ticker,
            "established_at": established,
            "last_updated": now,
            "summary": brief.get("thesis", existing.get("summary", "")),
            "conviction": brief.get("conviction", existing.get("conviction", 0)),
            "short_term_event_conviction": brief.get(
                "short_term_event_conviction",
                existing.get("short_term_event_conviction", 0),
            ),
            "recovery_thesis": brief.get("recovery_thesis", ""),
            "key_drivers": brief.get("key_drivers", existing.get("key_drivers", [])),
            "key_risks": brief.get("key_risks", existing.get("key_risks", [])),
            "proposed_driver_deltas": brief.get(
                "proposed_driver_deltas",
                existing.get("proposed_driver_deltas", {}),
            ),
            "rationale_for_deltas": brief.get(
                "rationale_for_deltas",
                existing.get("rationale_for_deltas", ""),
            ),
            "model_financials": model_fin,
            "suggested_multiples": suggested,
            "multiples_implied_prices": implied_prices,
            "current_price": financials.get("current_price") if financials else None,
            "recommended_dollars": brief.get("recommended_dollars", 0),
            "recommended_weight": brief.get("recommended_weight", 0),
            "challenge_to_others": brief.get("challenge_to_others", ""),
            "seen_headlines": existing.get("seen_headlines", []),
            "confidence": brief.get("conviction", existing.get("confidence", 0)),
        }

        view_path.write_text(json.dumps(view, indent=2, default=str))
        print("  [finalize] Updated analyst view: %s" % view_path.name)


def build_graph():
    """Build and compile PM-led portfolio-allocation graph for LangSmith Cloud."""
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

    # PM finalization
    graph.add_node("pm_debate_and_allocate", _pm_debate_and_allocate)
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

    # Fan in to PM
    graph.add_edge("analyze_nvda", "pm_debate_and_allocate")
    graph.add_edge("analyze_cdns", "pm_debate_and_allocate")
    graph.add_edge("analyze_crwv", "pm_debate_and_allocate")
    graph.add_edge("analyze_tsm", "pm_debate_and_allocate")
    graph.add_edge("analyze_asml", "pm_debate_and_allocate")

    graph.add_edge("pm_debate_and_allocate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


graph = build_graph()
