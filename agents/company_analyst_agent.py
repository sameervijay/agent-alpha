"""
Company News Analyst Agent — fetches real-world news from IR pages, SEC filings,
and financial news sources, then synthesizes into structured DCF driver updates.

Two operating modes:
  - RAMP:    First time on a ticker. Deep research, establishes baseline view
             across all drivers/periods. Saves view to disk.
  - MONITOR: Subsequent runs. Fetches new news, compares against seen headlines.
             Only calls LLM if there is genuinely new material. Updates the
             persisted view if warranted, otherwise returns the existing view.
"""

from __future__ import annotations

import json
from datetime import datetime

from agents.base_agent import BaseAgent
from models.event import Event
from models.causal_graph import CausalLink
from models.news_item import NewsItem, DriverUpdatePackage, AnalystView
from tools.news_fetcher import fetch_all_news
import config

VALID_DRIVERS = {
    'datacenter_growth', 'gaming_growth', 'automotive_growth',
    'proviz_growth', 'oem_growth',
    'gm_improvement_bps', 'rd_improvement_bps', 'sga_improvement_bps',
}

VALID_PERIODS = {
    'Q4-26', 'Q1-27', 'Q2-27', 'Q3-27', 'Q4-27',
    'FY2028', 'FY2029', 'FY2030',
}


def _make_system_prompt(ticker: str) -> str:
    company_info = config.COMPANIES.get(ticker, {})
    name = company_info.get('name', ticker)
    sector = company_info.get('sector', 'Semiconductors')
    segments = company_info.get('segments', [])

    return f"""You are a Company News Analyst specializing in {name} ({ticker}).
Sector: {sector}
Business segments: {', '.join(segments)}

Your role:
1. Analyze recent company-specific news (IR releases, SEC filings, financial headlines)
2. Identify material developments that affect the company's financial outlook
3. Map news to specific DCF driver adjustments with clear rationale
4. Distinguish between noise and signal — only recommend changes for material news

Available DCF drivers:
- Revenue growth: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth
- Margin changes: gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030

You are conservative and evidence-based. Only recommend driver changes backed by specific news.
Provide confidence levels (0.0-1.0) reflecting the reliability of the underlying news."""


def _validate_drivers(raw_updates: dict, agent_name: str) -> dict:
    """Validate and strip invalid driver names, periods, and non-numeric values."""
    validated = {}
    for driver, periods in raw_updates.items():
        if driver not in VALID_DRIVERS:
            print(f"  [{agent_name}] Stripping invalid driver: {driver}")
            continue
        valid_periods = {}
        if isinstance(periods, dict):
            for period, value in periods.items():
                if period not in VALID_PERIODS:
                    print(f"  [{agent_name}] Stripping invalid period: {period}")
                    continue
                try:
                    valid_periods[period] = float(value)
                except (ValueError, TypeError):
                    print(f"  [{agent_name}] Stripping non-numeric value for {driver}[{period}]")
        if valid_periods:
            validated[driver] = valid_periods
    return validated


class CompanyAnalystAgent(BaseAgent):
    """Company-specific news analyst with ramp/monitor modes."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        company_info = config.COMPANIES.get(ticker, {})
        name = company_info.get('name', ticker)

        super().__init__(
            name=f"analyst_{ticker.lower()}",
            role_description=f"Company News Analyst — {name} ({ticker})",
            system_prompt=_make_system_prompt(ticker),
        )
        self._cached_news: list = []
        self._view_path = config.ANALYST_VIEWS_DIR / f"{ticker}_view.json"

    # ───────────────────────────────────────────────────────────
    # Persistence helpers
    # ───────────────────────────────────────────────────────────

    def _load_view(self) -> AnalystView | None:
        """Load persisted view from disk, or None if no view exists."""
        if self._view_path.exists():
            try:
                return AnalystView.load(str(self._view_path))
            except Exception as e:
                print(f"  [{self.name}] Corrupt view file, will re-ramp: {e}")
        return None

    def _save_view(self, view: AnalystView):
        view.save(str(self._view_path))

    @property
    def has_view(self) -> bool:
        return self._view_path.exists()

    # ───────────────────────────────────────────────────────────
    # News gathering (shared by both modes)
    # ───────────────────────────────────────────────────────────

    def gather_news(self) -> list:
        """Fetch news from IR/SEC/finviz and convert to NewsItem instances."""
        raw_items = fetch_all_news(self.ticker)
        news_items = []
        for item in raw_items:
            try:
                news_items.append(NewsItem.from_dict(item))
            except Exception:
                news_items.append(NewsItem(
                    headline=item.get('headline', ''),
                    url=item.get('url', ''),
                    date=item.get('date', ''),
                    source=item.get('source', 'unknown'),
                    ticker=self.ticker,
                    summary=item.get('summary', ''),
                    form_type=item.get('form_type'),
                ))
        self._cached_news = news_items
        return news_items

    # ───────────────────────────────────────────────────────────
    # RAMP MODE — establish baseline view
    # ───────────────────────────────────────────────────────────

    def ramp(self, news_items: list = None) -> AnalystView:
        """Deep research pass: establish a full baseline view across all drivers/periods.
        Saves view to disk. Returns the AnalystView.
        """
        if news_items is None:
            news_items = self.gather_news()

        print(f"  [{self.name}] RAMP mode — establishing baseline view for {self.ticker}")

        news_text = self._format_news_for_prompt(news_items)

        company_info = config.COMPANIES.get(self.ticker, {})
        segments = company_info.get('segments', [])

        prompt = f"""You are ramping on {self.ticker} as a new coverage analyst. Establish your baseline view.

RECENT NEWS & FILINGS:{news_text}

COMPANY SEGMENTS: {', '.join(segments)}

Establish a comprehensive baseline view across ALL relevant drivers and periods.
Think like a sell-side analyst initiating coverage:
1. What is the current revenue trajectory for each segment?
2. Are margins expanding or contracting, and why?
3. What catalysts or risks are visible in the next 6-18 months?

Return a JSON object with:
- summary: 3-5 sentence thesis on {self.ticker} — your overall view
- baseline_drivers: object mapping driver_name -> object mapping period -> delta_value
  Cover ALL drivers relevant to this company across multiple periods.
  Revenue growth deltas are in decimal (0.05 = +5pp growth above consensus)
  Margin bps deltas are in basis points (50 = +50bps improvement vs consensus)
  Use 0.0 for drivers where you have no basis to deviate from consensus.
- rationale: object mapping each driver_name with a non-zero value -> 1-2 sentence justification
- confidence: float 0.0 to 1.0 (overall confidence in your baseline view)

Valid driver names: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030"""

        result = self.call_llm_json(prompt)

        validated_drivers = _validate_drivers(result.get('baseline_drivers', {}), self.name)
        raw_rationale = result.get('rationale', {})
        validated_rationale = {k: v for k, v in raw_rationale.items() if k in VALID_DRIVERS}

        view = AnalystView(
            ticker=self.ticker,
            summary=result.get('summary', ''),
            baseline_drivers=validated_drivers,
            rationale=validated_rationale,
            confidence=float(result.get('confidence', 0.0)),
            seen_headlines=[n.headline for n in news_items],
        )

        self._save_view(view)
        print(f"  [{self.name}] Baseline view saved ({len(validated_drivers)} drivers)")
        return view

    # ───────────────────────────────────────────────────────────
    # MONITOR MODE — check for material updates
    # ───────────────────────────────────────────────────────────

    def monitor(self, news_items: list = None) -> AnalystView:
        """Check for new news since last run. Only calls LLM if new material exists.
        Returns the (possibly updated) AnalystView.
        """
        view = self._load_view()
        if view is None:
            print(f"  [{self.name}] No existing view — falling back to ramp")
            return self.ramp(news_items)

        if news_items is None:
            news_items = self.gather_news()

        # Find headlines we haven't seen before
        seen = set(view.seen_headlines)
        new_items = [n for n in news_items if n.headline not in seen]

        if not new_items:
            print(f"  [{self.name}] MONITOR — no new headlines, view unchanged")
            return view

        print(f"  [{self.name}] MONITOR — {len(new_items)} new headline(s) found")

        new_news_text = self._format_news_for_prompt(new_items)
        current_view_text = json.dumps({
            'summary': view.summary,
            'baseline_drivers': view.baseline_drivers,
            'rationale': view.rationale,
            'confidence': view.confidence,
        }, indent=2)

        prompt = f"""You are monitoring {self.ticker}. You have an existing baseline view and new news has come in.

YOUR CURRENT VIEW:
{current_view_text}

NEW NEWS (not seen before):{new_news_text}

Decide: does any of this new news MATERIALLY change your view on any driver?
Material = would move a driver value by a meaningful amount, not noise.

Return a JSON object with:
- material_change: boolean — true if your view should be updated, false if this is noise
- updated_summary: your revised summary (or repeat the old one if no change)
- updated_drivers: the FULL driver map (existing values + any changes). Only change values where the news warrants it.
- updated_rationale: rationale for any CHANGED drivers (keep existing rationale for unchanged)
- confidence: float 0.0 to 1.0
- change_explanation: 1-2 sentences on what changed and why (or "No material change")

Valid driver names: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030"""

        result = self.call_llm_json(prompt)

        material = result.get('material_change', False)
        explanation = result.get('change_explanation', '')

        if not material:
            print(f"  [{self.name}] No material change: {explanation}")
            # Still update seen headlines so we don't re-check them
            view.seen_headlines.extend([n.headline for n in new_items])
            view.last_updated = datetime.now().isoformat()
            self._save_view(view)
            return view

        print(f"  [{self.name}] Material update: {explanation}")

        validated_drivers = _validate_drivers(result.get('updated_drivers', {}), self.name)
        raw_rationale = result.get('updated_rationale', {})
        validated_rationale = {k: v for k, v in raw_rationale.items() if k in VALID_DRIVERS}

        view.summary = result.get('updated_summary', view.summary)
        view.baseline_drivers = validated_drivers
        view.rationale = validated_rationale
        view.confidence = float(result.get('confidence', view.confidence))
        view.seen_headlines.extend([n.headline for n in new_items])
        view.last_updated = datetime.now().isoformat()

        self._save_view(view)
        print(f"  [{self.name}] View updated and saved")
        return view

    # ───────────────────────────────────────────────────────────
    # Main entry point — auto-detects mode
    # ───────────────────────────────────────────────────────────

    def produce_driver_update(self) -> DriverUpdatePackage:
        """Auto-detect ramp vs monitor, run appropriate mode, return DriverUpdatePackage."""
        try:
            news_items = self.gather_news()
            if not news_items:
                print(f"  [{self.name}] No news found for {self.ticker}")
                if self.has_view:
                    return self._load_view().to_driver_update_package()
                return DriverUpdatePackage.empty(self.ticker)

            if self.has_view:
                view = self.monitor(news_items)
            else:
                view = self.ramp(news_items)

            return view.to_driver_update_package()
        except Exception as e:
            print(f"  [{self.name}] Error producing driver update: {e}")
            return DriverUpdatePackage.empty(self.ticker)

    # ───────────────────────────────────────────────────────────
    # Prompt formatting helper
    # ───────────────────────────────────────────────────────────

    def _format_news_for_prompt(self, news_items: list, max_items: int = 15) -> str:
        """Format news items into a compact string for LLM prompts."""
        text = ""
        for i, item in enumerate(news_items[:max_items], 1):
            summary = (item.summary or item.headline)[:150]
            date_str = item.date[:10] if item.date else 'N/A'
            text += f"\n{i}. [{item.source}] {date_str} | {item.headline[:120]}"
            if summary != item.headline[:150]:
                text += f"\n   Summary: {summary}"
        return text

    # ───────────────────────────────────────────────────────────
    # Standard 3-method interface (PM treats like domain agents)
    # ───────────────────────────────────────────────────────────

    def detect_events(self, news_input: str) -> list:
        """Phase 1: Enrich PM's input with fetched IR news, return Events."""
        news_items = self.gather_news()
        news_context = ""
        if news_items:
            headlines = [f"- {n.headline}" for n in news_items[:10]]
            news_context = f"\n\nRecent {self.ticker} news from IR/SEC/finviz:\n" + "\n".join(headlines)

        prompt = f"""Analyze the following scenario combined with recent company news for {self.ticker}.

SCENARIO:
{news_input}
{news_context}

Return a JSON object with key "events", where each event has:
- headline: concise event title
- description: 2-3 sentence explanation
- affected_companies: list of tickers (from NVDA, TSM, ASML, CDNS, CRWV)
- affected_segments: list of business segments affected
- severity: one of "low", "medium", "high", "critical"
- direction: one of "positive", "negative", "neutral", "mixed"

Only include events relevant to {self.ticker} and backed by specific news. If no relevant events, return empty list."""

        data = self.call_llm_json(prompt)
        events = []
        for e in data.get('events', []):
            events.append(Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=self.name,
                affected_companies=e.get('affected_companies', [self.ticker]),
                affected_segments=e.get('affected_segments', []),
                severity=e.get('severity', 'medium'),
                direction=e.get('direction', 'neutral'),
                raw_input=news_input,
            ))
        return events

    def build_causal_links(self, event: Event) -> list:
        """Phase 2: Use cached news as additional context for causal reasoning."""
        news_context = ""
        if self._cached_news:
            headlines = [f"- [{n.source}] {n.headline}" for n in self._cached_news[:10]]
            news_context = f"\n\nRecent {self.ticker} news context:\n" + "\n".join(headlines)

        prompt = f"""Given this event and recent company news, trace causal chains to financial impacts on {self.ticker}.

EVENT: {event.headline}
DESCRIPTION: {event.description}
{news_context}

Return a JSON object with key "causal_links", where each link has:
- source_event: the event headline
- intermediate_step: business mechanism connecting event to metric
- downstream_metric: one of datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
- affected_company: "{self.ticker}"
- affected_periods: list of periods (from Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030)
- direction: "increase" or "decrease"
- magnitude_estimate: quantitative estimate like "-5pp" or "+100bps"
- confidence: float 0.0 to 1.0
- reasoning: 2-3 sentence justification citing specific news where possible"""

        data = self.call_llm_json(prompt)
        links = []
        for l in data.get('causal_links', []):
            links.append(CausalLink(
                source_event=l['source_event'],
                intermediate_step=l['intermediate_step'],
                downstream_metric=l['downstream_metric'],
                affected_company=l.get('affected_company', self.ticker),
                affected_periods=l['affected_periods'],
                direction=l['direction'],
                magnitude_estimate=l['magnitude_estimate'],
                confidence=l['confidence'],
                reasoning=l['reasoning'],
                proposed_by=self.name,
            ))
        return links

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        """Phase 3: Only debate for own ticker; return empty dict for other companies."""
        if company != self.ticker:
            return {}

        others_text = ""
        for p in other_positions:
            others_text += (f"\n  - {p['agent_name']}: value={p['proposed_value']}, "
                          f"confidence={p['confidence']}, "
                          f"reasoning={p['reasoning'][:200]}")

        news_context = ""
        if self._cached_news:
            headlines = [f"- {n.headline}" for n in self._cached_news[:8]]
            news_context = f"\n\nRecent {self.ticker} news:\n" + "\n".join(headlines)

        prompt = f"""You are debating the impact on a specific financial metric, informed by recent company news.

EVENT: {event.headline}
DESCRIPTION: {event.description}
METRIC: {metric}
COMPANY: {company}
PERIOD: {period}
{news_context}

Other agents' positions:{others_text if others_text else " (You are the first to respond)"}

From your company-specific analysis and recent news, provide your position on how this event affects {metric} for {company} in {period}.

Return a JSON object with:
- proposed_value: float (delta to apply — e.g., -0.05 for 5pp decrease, or 50 for +50bps)
- confidence: float 0.0 to 1.0
- reasoning: 3-5 sentence justification citing specific news
- data_type: "leading" or "lagging"
- challenges: any challenges to other agents' positions (or empty string)"""

        return self.call_llm_json(prompt)
