"""
Independent Macro Analyst Agent — monitors macro indicators, persists a macro view,
pushes alerts to company analysts on material changes, and produces nightly briefings.

Two operating modes (like CompanyAnalystAgent):
  - RAMP:    First run. Gathers all indicators, LLM establishes baseline thesis.
  - MONITOR: Subsequent runs. Compares current vs previous. Only calls LLM if
             indicators moved beyond thresholds. Generates alerts if material.

Also implements the standard 3-method debate interface so it can optionally
participate in pipeline debates alongside the existing MacroAgent.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

from agents.base_agent import BaseAgent
from models.macro_view import MacroSnapshot, MacroView, MacroAlert, MacroBriefing
from models.event import Event
from models.causal_graph import CausalLink
from tools import fred_data, market_data
from tools.macro_news_fetcher import fetch_all_macro_news
import config
import macro_analyst_config as mcfg


MACRO_SYSTEM_PROMPT = """You are an Independent Macro Analyst monitoring the global macroeconomic environment
and its impact on the semiconductor value chain.

Your coverage universe: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

Your domain expertise:
- Federal Reserve policy (fed funds rate, QT/QE, forward guidance)
- Treasury yields (2Y, 10Y) and yield curve shape
- GDP growth and economic cycle positioning
- Inflation (CPI, PPI, PCE) and real interest rates
- Corporate capex cycles and IT budget trends
- Currency effects on global semiconductor companies
- Data center capex trends from hyperscalers

Available DCF drivers you can map to:
- Revenue growth: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth
- Margin changes: gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030

You are rigorous and data-driven. Only flag changes that are truly material.
""" + mcfg.SYSTEM_PROMPT_ADDENDUM


class MacroAnalystAgent(BaseAgent):
    """Independent macro analyst with ramp/monitor modes and alert/briefing capabilities."""

    def __init__(self):
        super().__init__(
            name="macro_analyst",
            role_description="Independent Macro Analyst — Rates, Fed Policy, GDP, Inflation",
            system_prompt=MACRO_SYSTEM_PROMPT,
        )
        self._view_path = config.MACRO_ANALYST_DIR / 'macro_view.json'
        self._alerts_dir = config.MACRO_ANALYST_DIR / 'alerts'
        self._briefings_dir = config.MACRO_ANALYST_DIR / 'briefings'
        self._alerts_dir.mkdir(parents=True, exist_ok=True)
        self._briefings_dir.mkdir(parents=True, exist_ok=True)

    # ───────────────────────────────────────────────────────────
    # Persistence helpers
    # ───────────────────────────────────────────────────────────

    def _load_view(self) -> Optional[MacroView]:
        if self._view_path.exists():
            try:
                return MacroView.load(str(self._view_path))
            except Exception as e:
                print(f"  [{self.name}] Corrupt view file, will re-ramp: {e}")
        return None

    def _save_view(self, view: MacroView):
        view.save(str(self._view_path))

    @property
    def has_view(self) -> bool:
        return self._view_path.exists()

    # ───────────────────────────────────────────────────────────
    # Data gathering
    # ───────────────────────────────────────────────────────────

    def gather_macro_data(self) -> MacroSnapshot:
        """Fetch all FRED indicators and sector performance. Returns MacroSnapshot."""
        print(f"  [{self.name}] Gathering macro data from FRED + market data...")
        indicators = {}
        for key, info in mcfg.TRACKED_INDICATORS.items():
            val = fred_data.get_latest(info['fred_key'])
            indicators[key] = val
            print(f"    {info['label']}: {val} {info['unit']}")

        sector_perf = {}
        for period in ['1mo', '3mo']:
            result = market_data.get_sector_performance(period)
            ret = result.get('return', 0)
            sector_perf[period] = ret
            print(f"    Semiconductor sector ({period}): {ret:+.2%}")

        # Fetch macro news
        news_items = []
        try:
            news_items = fetch_all_macro_news()
        except Exception as e:
            print(f"  [{self.name}] Macro news fetch failed (non-fatal): {e}")

        return MacroSnapshot(
            timestamp=datetime.now().isoformat(),
            indicators=indicators,
            sector_performance=sector_perf,
            news_items=news_items,
        )

    # ───────────────────────────────────────────────────────────
    # RAMP MODE — establish baseline macro thesis
    # ───────────────────────────────────────────────────────────

    def ramp(self) -> MacroView:
        """First run: gather data, LLM establishes baseline thesis. Saves MacroView."""
        snapshot = self.gather_macro_data()
        print(f"  [{self.name}] RAMP mode — establishing baseline macro thesis")

        indicator_text = self._format_indicators(snapshot)
        news_text = self._format_macro_news(snapshot.news_items)
        tickers = ', '.join(mcfg.ALERT_RECIPIENT_TICKERS)

        prompt = f"""You are establishing your baseline macro thesis for the semiconductor value chain.

CURRENT MACRO INDICATORS:
{indicator_text}

SEMICONDUCTOR SECTOR PERFORMANCE:
{self._format_sector_perf(snapshot)}

RECENT MACRO NEWS:
{news_text}

COVERAGE UNIVERSE: {tickers}

Establish a comprehensive macro baseline:
1. What is the current macro regime (growth, inflation, rates)?
2. What is the yield curve signaling?
3. How do current conditions affect semiconductor demand and valuations?
4. What are the key risks and themes?

Return a JSON object with:
- summary: 3-5 sentence macro thesis
- outlook: one of "bullish", "bearish", "neutral", "cautious"
- key_themes: list of 3-5 macro themes (e.g., "Fed pause supports tech valuations")
- risk_factors: list of 3-5 risks
- company_implications: object mapping each ticker to a 1-2 sentence implication
  (tickers: {tickers})
- confidence: float 0.0 to 1.0"""

        print(f"  [{self.name}] Calling LLM for baseline macro analysis...")
        result = self.call_llm_json(prompt)

        # Build indicator history with initial reading
        indicator_history = {}
        for key, val in snapshot.indicators.items():
            indicator_history[key] = [{'timestamp': snapshot.timestamp, 'value': val}]

        view = MacroView(
            summary=result.get('summary', ''),
            outlook=result.get('outlook', 'neutral'),
            key_themes=result.get('key_themes', []),
            risk_factors=result.get('risk_factors', []),
            indicator_history=indicator_history,
            company_implications=result.get('company_implications', {}),
            confidence=float(result.get('confidence', 0.5)),
            seen_headlines=[item.get('headline', '') for item in snapshot.news_items if item.get('headline')],
        )

        self._save_view(view)
        print(f"  [{self.name}] Baseline macro view saved (outlook: {view.outlook}, "
              f"confidence: {view.confidence:.0%})")
        return view

    # ───────────────────────────────────────────────────────────
    # MONITOR MODE — check for material changes
    # ───────────────────────────────────────────────────────────

    def monitor(self) -> Tuple[MacroView, List[MacroAlert]]:
        """Compare current snapshot vs previous. If indicators moved beyond
        thresholds, LLM reassesses. Returns (MacroView, list[MacroAlert]).
        No LLM call if nothing moved.
        """
        view = self._load_view()
        if view is None:
            print(f"  [{self.name}] No existing view — falling back to ramp")
            return self.ramp(), []

        snapshot = self.gather_macro_data()

        # Detect material changes
        changes = self._detect_material_changes(snapshot, view)

        # Detect new headlines
        seen = set(view.seen_headlines)
        new_headlines = [item for item in snapshot.news_items
                         if item.get('headline') and item['headline'] not in seen]

        if not changes and not new_headlines:
            print(f"  [{self.name}] MONITOR — no material indicator changes or new headlines, view unchanged")
            # Still update indicator history
            self._append_indicator_history(view, snapshot)
            view.last_updated = datetime.now().isoformat()
            self._save_view(view)
            return view, []

        if changes:
            print(f"  [{self.name}] MONITOR — {len(changes)} material change(s) detected:")
            for c in changes:
                print(f"    {c['label']}: {c['previous']:.2f} -> {c['current']:.2f} "
                      f"(delta: {c['delta']:+.2f}, threshold: {c['threshold']})")
        if new_headlines:
            print(f"  [{self.name}] MONITOR — {len(new_headlines)} new headline(s) detected")

        # LLM reassesses
        indicator_text = self._format_indicators(snapshot)
        news_text = self._format_macro_news(new_headlines)
        changes_text = json.dumps(changes, indent=2) if changes else "None"
        current_view_text = json.dumps({
            'summary': view.summary,
            'outlook': view.outlook,
            'key_themes': view.key_themes,
            'risk_factors': view.risk_factors,
            'company_implications': view.company_implications,
        }, indent=2)
        tickers = ', '.join(mcfg.ALERT_RECIPIENT_TICKERS)

        prompt = f"""You are monitoring macro conditions. Material changes or new news have been detected.

YOUR CURRENT VIEW:
{current_view_text}

CURRENT INDICATORS:
{indicator_text}

MATERIAL CHANGES DETECTED:
{changes_text}

NEW MACRO NEWS:
{news_text}

Reassess your macro view given these changes.

Return a JSON object with:
- summary: updated 3-5 sentence macro thesis
- outlook: one of "bullish", "bearish", "neutral", "cautious"
- key_themes: updated list of 3-5 themes
- risk_factors: updated list of 3-5 risks
- company_implications: updated object mapping each ticker to a 1-2 sentence implication
  (tickers: {tickers})
- confidence: float 0.0 to 1.0
- alerts: list of alert objects for MATERIAL changes that company analysts should act on.
  Each alert has:
  - severity: "low", "medium", "high", or "critical"
  - headline: concise alert title
  - description: 2-3 sentence explanation
  - affected_indicators: list of indicator keys that triggered this
  - target_tickers: list of tickers most affected
  - suggested_driver_impacts: object mapping driver_name -> {{period: delta_value}}
    (use valid drivers: datacenter_growth, gaming_growth, automotive_growth, proviz_growth,
     oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps)
    (valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030)
  - confidence: float 0.0 to 1.0
  Only generate alerts for changes that would materially affect company valuations."""

        print(f"  [{self.name}] Calling LLM for reassessment...")
        result = self.call_llm_json(prompt)

        # Update view
        view.summary = result.get('summary', view.summary)
        view.outlook = result.get('outlook', view.outlook)
        view.key_themes = result.get('key_themes', view.key_themes)
        view.risk_factors = result.get('risk_factors', view.risk_factors)
        view.company_implications = result.get('company_implications', view.company_implications)
        view.confidence = float(result.get('confidence', view.confidence))
        view.last_updated = datetime.now().isoformat()
        self._append_indicator_history(view, snapshot)

        # Update seen headlines
        for item in snapshot.news_items:
            hl = item.get('headline', '')
            if hl and hl not in view.seen_headlines:
                view.seen_headlines.append(hl)

        self._save_view(view)
        print(f"  [{self.name}] Macro view updated (outlook: {view.outlook})")

        # Generate and save alerts
        alerts = self._generate_alerts(result.get('alerts', []))
        if alerts:
            print(f"  [{self.name}] Generated {len(alerts)} alert(s)")
        return view, alerts

    def _detect_material_changes(self, snapshot: MacroSnapshot,
                                  view: MacroView) -> List[dict]:
        """Numeric comparison per indicator against config thresholds."""
        changes = []
        for key, info in mcfg.TRACKED_INDICATORS.items():
            current = snapshot.indicators.get(key, 0)
            # Get previous value from indicator history
            history = view.indicator_history.get(key, [])
            if not history:
                continue
            previous = history[-1].get('value', 0)
            delta = abs(current - previous)
            threshold = info['threshold']
            if delta >= threshold:
                changes.append({
                    'indicator': key,
                    'label': info['label'],
                    'previous': previous,
                    'current': current,
                    'delta': current - previous,
                    'threshold': threshold,
                    'unit': info['unit'],
                })
        return changes

    def _generate_alerts(self, raw_alerts: list) -> List[MacroAlert]:
        """Parse LLM alert output, validate, save to disk."""
        alerts = []
        for a in raw_alerts:
            confidence = float(a.get('confidence', 0.5))
            if confidence < mcfg.ALERT_CONFIDENCE_THRESHOLD:
                continue

            alert = MacroAlert(
                severity=a.get('severity', 'medium'),
                headline=a.get('headline', ''),
                description=a.get('description', ''),
                affected_indicators=a.get('affected_indicators', []),
                suggested_driver_impacts=a.get('suggested_driver_impacts', {}),
                target_tickers=a.get('target_tickers', mcfg.ALERT_RECIPIENT_TICKERS),
                confidence=confidence,
            )

            # Save alert to disk
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{alert.id}.json"
            filepath = self._alerts_dir / filename
            alert.save(str(filepath))
            print(f"    Alert saved: {alert.headline} (severity: {alert.severity})")
            alerts.append(alert)

        return alerts

    def _append_indicator_history(self, view: MacroView, snapshot: MacroSnapshot):
        """Append current snapshot values to indicator history."""
        for key, val in snapshot.indicators.items():
            if key not in view.indicator_history:
                view.indicator_history[key] = []
            view.indicator_history[key].append({
                'timestamp': snapshot.timestamp,
                'value': val,
            })

    # ───────────────────────────────────────────────────────────
    # Nightly briefing
    # ───────────────────────────────────────────────────────────

    def produce_nightly_briefing(self) -> MacroBriefing:
        """LLM generates comprehensive overview with per-company notes. Saves MacroBriefing."""
        view = self._load_view()
        if view is None:
            print(f"  [{self.name}] No macro view — run ramp first")
            view = self.ramp()

        snapshot = self.gather_macro_data()

        # Build indicator table
        indicator_table = []
        for key, info in mcfg.TRACKED_INDICATORS.items():
            current = snapshot.indicators.get(key, 0)
            history = view.indicator_history.get(key, [])
            previous = history[-1].get('value', 0) if history else 0
            change = current - previous
            indicator_table.append({
                'indicator': key,
                'label': info['label'],
                'current': current,
                'previous': previous,
                'change': change,
                'unit': info['unit'],
            })

        table_text = json.dumps(indicator_table, indent=2)
        news_text = self._format_macro_news(snapshot.news_items)
        tickers = ', '.join(mcfg.BRIEFING_RECIPIENT_TICKERS)

        prompt = f"""Produce a nightly macro briefing for the semiconductor investment team.

CURRENT MACRO VIEW:
Summary: {view.summary}
Outlook: {view.outlook}
Themes: {json.dumps(view.key_themes)}
Risks: {json.dumps(view.risk_factors)}

INDICATOR TABLE (current vs previous reading):
{table_text}

RECENT MACRO NEWS:
{news_text}

SEMICONDUCTOR SECTOR PERFORMANCE:
{self._format_sector_perf(snapshot)}

COVERAGE UNIVERSE: {tickers}

Return a JSON object with:
- macro_summary: 4-6 sentence briefing on today's macro environment
- outlook: one of "bullish", "bearish", "neutral", "cautious"
- company_notes: object mapping each ticker to a 2-3 sentence note on macro implications
  (tickers: {tickers})
- risk_factors: list of 3-5 current risk factors
- key_themes: list of 3-5 key macro themes"""

        print(f"  [{self.name}] Generating nightly briefing...")
        result = self.call_llm_json(prompt)

        briefing = MacroBriefing(
            macro_summary=result.get('macro_summary', ''),
            outlook=result.get('outlook', view.outlook),
            indicator_table=indicator_table,
            company_notes=result.get('company_notes', {}),
            risk_factors=result.get('risk_factors', []),
            key_themes=result.get('key_themes', []),
        )

        # Save briefing
        filename = f"{datetime.now().strftime('%Y%m%d')}_briefing.json"
        filepath = self._briefings_dir / filename
        briefing.save(str(filepath))
        print(f"  [{self.name}] Nightly briefing saved to {filepath}")

        # Update indicator history
        self._append_indicator_history(view, snapshot)
        view.last_updated = datetime.now().isoformat()
        self._save_view(view)

        return briefing

    # ───────────────────────────────────────────────────────────
    # Pure read methods (no LLM calls)
    # ───────────────────────────────────────────────────────────

    def get_current_view(self) -> Optional[MacroView]:
        """Pure file read for PM. No LLM call."""
        return self._load_view()

    def get_view_summary(self) -> dict:
        """Compact dict for PM display. No LLM call."""
        view = self._load_view()
        if view is None:
            return {'status': 'no_view', 'summary': 'Macro analyst has not been initialized'}
        return {
            'status': 'active',
            'outlook': view.outlook,
            'summary': view.summary,
            'key_themes': view.key_themes,
            'risk_factors': view.risk_factors[:3],
            'confidence': view.confidence,
            'last_updated': view.last_updated,
        }

    def get_pending_alerts(self, ticker: str = None) -> List[MacroAlert]:
        """Load unacknowledged alerts from disk. Optionally filter by ticker."""
        alerts = []
        if not self._alerts_dir.exists():
            return alerts
        for fp in sorted(self._alerts_dir.glob('*.json')):
            try:
                alert = MacroAlert.load(str(fp))
                if alert.acknowledged:
                    continue
                if ticker and ticker not in alert.target_tickers:
                    continue
                alerts.append(alert)
            except Exception:
                continue
        return alerts

    def acknowledge_alert(self, alert_id: str, response: str = "") -> bool:
        """Mark an alert as acknowledged. Returns True if found and updated."""
        for fp in self._alerts_dir.glob('*.json'):
            try:
                alert = MacroAlert.load(str(fp))
                if alert.id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledgement_response = response
                    alert.save(str(fp))
                    return True
            except Exception:
                continue
        return False

    def get_latest_briefing(self) -> Optional[MacroBriefing]:
        """Load the most recent briefing from disk. No LLM call."""
        if not self._briefings_dir.exists():
            return None
        files = sorted(self._briefings_dir.glob('*_briefing.json'), reverse=True)
        if not files:
            return None
        try:
            return MacroBriefing.load(str(files[0]))
        except Exception:
            return None

    # ───────────────────────────────────────────────────────────
    # Main entry point — auto-detects ramp vs monitor
    # ───────────────────────────────────────────────────────────

    def run(self) -> Tuple[MacroView, List[MacroAlert]]:
        """Auto-detect ramp vs monitor, run appropriate mode."""
        if self.has_view:
            print(f"  [{self.name}] Existing view found -> MONITOR mode")
            return self.monitor()
        else:
            print(f"  [{self.name}] No existing view -> RAMP mode")
            return self.ramp(), []

    # ───────────────────────────────────────────────────────────
    # Formatting helpers
    # ───────────────────────────────────────────────────────────

    def _format_indicators(self, snapshot: MacroSnapshot) -> str:
        lines = []
        for key, val in snapshot.indicators.items():
            info = mcfg.TRACKED_INDICATORS.get(key, {})
            label = info.get('label', key)
            unit = info.get('unit', '')
            lines.append(f"  {label}: {val} {unit}")
        return '\n'.join(lines)

    def _format_macro_news(self, news_items: list) -> str:
        """Format news dicts for inclusion in LLM prompts."""
        if not news_items:
            return "  (no macro news available)"
        lines = []
        for item in news_items[:15]:
            headline = item.get('headline', '(no headline)')
            date = item.get('date', '')
            source = item.get('source', '')
            sentiment = item.get('sentiment', '')
            tag = f" [{sentiment}]" if sentiment else ""
            lines.append(f"  [{source}] {headline} ({date}){tag}")
        return '\n'.join(lines)

    def _format_sector_perf(self, snapshot: MacroSnapshot) -> str:
        lines = []
        for period, ret in snapshot.sector_performance.items():
            lines.append(f"  Semiconductor sector ({period}): {ret:+.2%}")
        return '\n'.join(lines)

    # ───────────────────────────────────────────────────────────
    # Standard 3-method debate interface (optional pipeline participation)
    # ───────────────────────────────────────────────────────────

    def detect_events(self, news_input: str) -> list:
        """Phase 1: Detect macro events, enriched with current indicator data and news."""
        snapshot = self.gather_macro_data()
        indicator_text = self._format_indicators(snapshot)
        news_text = self._format_macro_news(snapshot.news_items)

        prompt = f"""Analyze the following scenario for macroeconomic events relevant to semiconductor companies.

NEWS INPUT:
{news_input}

CURRENT MACRO INDICATORS:
{indicator_text}

RECENT MACRO NEWS:
{news_text}

Return a JSON object with key "events", where each event has:
- headline: concise event title
- description: 2-3 sentence explanation
- affected_companies: list of tickers (from NVDA, TSM, ASML, CDNS, CRWV)
- affected_segments: list of segments affected
- severity: "low", "medium", "high", or "critical"
- direction: "positive", "negative", "neutral", or "mixed"

Only include events relevant to macroeconomics and the semiconductor value chain."""

        data = self.call_llm_json(prompt)
        events = []
        for e in data.get('events', []):
            events.append(Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=self.name,
                affected_companies=e.get('affected_companies', []),
                affected_segments=e.get('affected_segments', []),
                severity=e.get('severity', 'medium'),
                direction=e.get('direction', 'neutral'),
                raw_input=news_input,
            ))
        return events

    def build_causal_links(self, event: Event) -> list:
        """Phase 2: Build causal links from a macro perspective."""
        view = self._load_view()
        view_context = ""
        if view:
            view_context = f"\n\nCurrent macro outlook: {view.outlook}\nThesis: {view.summary}"

        prompt = f"""Given this event, trace causal chains to financial impacts on semiconductor companies
from a macroeconomic perspective.

EVENT: {event.headline}
DESCRIPTION: {event.description}
AFFECTED COMPANIES: {', '.join(event.affected_companies)}
{view_context}

Return a JSON object with key "causal_links", where each link has:
- source_event: the event headline
- intermediate_step: economic mechanism
- downstream_metric: one of datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
- affected_company: ticker
- affected_periods: list of periods (from Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030)
- direction: "increase" or "decrease"
- magnitude_estimate: quantitative estimate like "-5pp" or "+100bps"
- confidence: float 0.0 to 1.0
- reasoning: justification"""

        data = self.call_llm_json(prompt)
        links = []
        for l in data.get('causal_links', []):
            links.append(CausalLink(
                source_event=l['source_event'],
                intermediate_step=l['intermediate_step'],
                downstream_metric=l['downstream_metric'],
                affected_company=l.get('affected_company', ''),
                affected_periods=l.get('affected_periods', []),
                direction=l['direction'],
                magnitude_estimate=l.get('magnitude_estimate', ''),
                confidence=float(l.get('confidence', 0.5)),
                reasoning=l.get('reasoning', ''),
                proposed_by=self.name,
            ))
        return links

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        """Phase 3: Macro-informed debate position."""
        view = self._load_view()
        view_context = ""
        if view:
            view_context = f"\nMacro outlook: {view.outlook}\nThesis: {view.summary}"

        others_text = ""
        for p in other_positions:
            others_text += (f"\n  - {p['agent_name']}: value={p['proposed_value']}, "
                          f"confidence={p['confidence']}, "
                          f"reasoning={p['reasoning'][:200]}")

        prompt = f"""You are debating the impact of an event on a financial metric from a macroeconomic perspective.

EVENT: {event.headline}
DESCRIPTION: {event.description}
METRIC: {metric}
COMPANY: {company}
PERIOD: {period}
{view_context}

Other agents' positions:{others_text if others_text else " (You are the first to respond)"}

Return a JSON object with:
- proposed_value: float (delta to apply)
- confidence: float 0.0 to 1.0
- reasoning: 3-5 sentence justification from macro perspective
- data_type: "leading" or "lagging"
- challenges: challenges to other positions"""

        return self.call_llm_json(prompt)
