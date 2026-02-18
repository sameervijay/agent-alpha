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

VALID_DRIVERS_BY_TICKER = {
    'NVDA': {
        'datacenter_growth', 'gaming_growth', 'automotive_growth',
        'proviz_growth', 'oem_growth',
        'gm_improvement_bps', 'rd_improvement_bps', 'sga_improvement_bps',
    },
    'CDNS': {
        'core_eda_growth', 'system_interconnect_growth', 'ip_growth',
        'gm_improvement_bps', 'rd_improvement_bps', 'ga_improvement_bps',
        'sm_improvement_bps',
    },
}

VALID_PERIODS_BY_TICKER = {
    'NVDA': {
        'Q4-26', 'Q1-27', 'Q2-27', 'Q3-27', 'Q4-27',
        'FY2028', 'FY2029', 'FY2030',
    },
    'CDNS': {
        'Q3-26', 'Q4-26',
        'FY2027', 'FY2028', 'FY2029',
    },
}


def _make_system_prompt(ticker: str) -> str:
    company_info = config.COMPANIES.get(ticker, {})
    name = company_info.get('name', ticker)
    sector = company_info.get('sector', 'Semiconductors')
    segments = company_info.get('segments', [])

    # Get ticker-specific drivers and periods
    valid_drivers = VALID_DRIVERS_BY_TICKER.get(ticker, set())
    valid_periods = VALID_PERIODS_BY_TICKER.get(ticker, set())

    # Format drivers by type
    rev_drivers = [d for d in valid_drivers if d.endswith('_growth')]
    margin_drivers = [d for d in valid_drivers if d.endswith('_bps')]

    return f"""You are a Company News Analyst specializing in {name} ({ticker}).
Sector: {sector}
Business segments: {', '.join(segments)}

Your role:
1. Analyze recent company-specific news (IR releases, SEC filings, financial headlines)
2. Identify material developments that affect the company's financial outlook
3. Map news to specific DCF driver adjustments with clear rationale
4. Distinguish between noise and signal — only recommend changes for material news

Available DCF drivers:
- Revenue growth: {', '.join(sorted(rev_drivers))}
- Margin changes: {', '.join(sorted(margin_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}

You are conservative and evidence-based. Only recommend driver changes backed by specific news.
Provide confidence levels (0.0-1.0) reflecting the reliability of the underlying news."""


def _validate_drivers(raw_updates: dict, agent_name: str, ticker: str) -> dict:
    """Validate and strip invalid driver names, periods, and non-numeric values."""
    valid_drivers = VALID_DRIVERS_BY_TICKER.get(ticker, set())
    valid_periods = VALID_PERIODS_BY_TICKER.get(ticker, set())

    validated = {}
    for driver, periods in raw_updates.items():
        if driver not in valid_drivers:
            print(f"  [{agent_name}] Stripping invalid driver for {ticker}: {driver}")
            continue
        valid_periods_dict = {}
        if isinstance(periods, dict):
            for period, value in periods.items():
                if period not in valid_periods:
                    print(f"  [{agent_name}] Stripping invalid period for {ticker}: {period}")
                    continue
                try:
                    valid_periods_dict[period] = float(value)
                except (ValueError, TypeError):
                    print(f"  [{agent_name}] Stripping non-numeric value for {driver}[{period}]")
        if valid_periods_dict:
            validated[driver] = valid_periods_dict
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
        self._write_summary_txt(view)

    def _write_summary_txt(self, view: AnalystView):
        """Write a human-readable text summary alongside the JSON view."""
        txt_path = config.ANALYST_VIEWS_DIR / f"{self.ticker}_summary.txt"
        sep = "=" * 80

        lines = [
            sep,
            f"  {self.ticker} — Company Analyst Summary",
            f"  Updated: {view.last_updated}",
            f"  Established: {view.established_at}",
            sep,
            "",
            f"CONFIDENCE: {view.confidence:.0%}",
            "",
            "THESIS:",
        ]
        for l in (view.summary or "(no summary)").split(". "):
            lines.append(f"  {l.strip()}")
        lines.append("")

        # Driver assumptions table
        all_periods = ['Q4-26', 'Q1-27', 'Q2-27', 'Q3-27', 'Q4-27',
                       'FY2028', 'FY2029', 'FY2030']
        present_periods = sorted(
            {p for drv in view.baseline_drivers.values() for p in drv},
            key=lambda p: all_periods.index(p) if p in all_periods else 99,
        )
        if present_periods:
            col_w = max(8, max(len(p) for p in present_periods) + 2)
            header = f"  {'Driver':<25s}| " + " | ".join(f"{p:>{col_w}s}" for p in present_periods)
            lines.append("DRIVER ASSUMPTIONS:")
            lines.append(header)
            lines.append("  " + "-" * (len(header) - 2))
            for driver in sorted(view.baseline_drivers):
                vals = view.baseline_drivers[driver]
                cells = []
                for p in present_periods:
                    v = vals.get(p)
                    cells.append(f"{v:>{col_w}.4f}" if v is not None else f"{'—':>{col_w}s}")
                lines.append(f"  {driver:<25s}| " + " | ".join(cells))
            lines.append("")

        # Rationale
        if view.rationale:
            lines.append("RATIONALE:")
            for driver, text in sorted(view.rationale.items()):
                lines.append(f"  {driver}: {text}")
            lines.append("")

        lines.append(f"NEWS TRACKED: {len(view.seen_headlines)} headlines processed")
        lines.append(sep)
        lines.append("")

        txt_path.write_text("\n".join(lines))

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
    # EXPERT CALL LEARNING
    # ───────────────────────────────────────────────────────────

    def learn_from_expert_call(self, expert_call_text: str) -> AnalystView:
        """
        Process expert call transcript and potentially update view.

        Takes expert calls with a grain of salt - they can provide useful
        context but should not drastically change views without strong corroboration.

        Args:
            expert_call_text: Full transcript of expert call

        Returns:
            Updated AnalystView (may be unchanged if call doesn't warrant update)
        """
        # Load current view
        view = self._load_view()
        if view is None:
            print(f"  [{self.name}] No existing view. Run ramp() first before processing expert calls.")
            return None

        print(f"  [{self.name}] Processing expert call for {self.ticker}...")

        # Get ticker-specific drivers and periods
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(self.ticker, set())

        current_view_text = json.dumps({
            'summary': view.summary,
            'baseline_drivers': view.baseline_drivers,
            'rationale': view.rationale,
            'confidence': view.confidence,
        }, indent=2)

        # Truncate expert call if too long (keep first 3000 chars)
        if len(expert_call_text) > 3000:
            expert_call_text = expert_call_text[:3000] + "\n\n[... transcript truncated ...]"

        prompt = f"""You are analyzing an expert call transcript for {self.ticker}. This is a call with a former industry insider.

YOUR CURRENT VIEW ON {self.ticker}:
{current_view_text}

EXPERT CALL TRANSCRIPT:
{expert_call_text}

IMPORTANT CONTEXT:
- Expert calls should be taken with a GRAIN OF SALT
- Experts may have outdated information (they are former employees)
- Experts may have biases or limited visibility into recent developments
- Use expert insights as ONE data point, not as the primary source of truth
- Only update your view if the expert provides CONCRETE, CREDIBLE insights that:
  1. Align with or strengthen trends you're already seeing in news
  2. Reveal material competitive positioning or product strategy shifts
  3. Highlight risks/opportunities you hadn't considered but can corroborate

Analyze the expert call and decide:
1. Does this call reveal any NEW material insights about {self.ticker}'s outlook?
2. Should you update ANY of your driver assumptions based on this?
3. How much weight should you give this expert's opinions vs your existing news-based view?

Return a JSON object with:
- warrants_change: boolean (true only if expert provides compelling, corroborated insights)
- updated_drivers: the FULL driver map (only modify values where expert provides credible new info)
- updated_summary: revised summary if warranted, incorporating expert context appropriately
- updated_rationale: rationale for any CHANGED drivers
- confidence: float 0.0 to 1.0 (may go DOWN if expert raises concerns, or UP if they validate your thesis)
- change_explanation: 2-4 sentences on what you learned and how much weight you gave it
- expert_credibility: float 0.0 to 1.0 (your assessment of how credible/relevant this expert's insights are)

Valid driver names: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}"""

        result = self.call_llm_json(prompt)

        warrants_change = result.get('warrants_change', False)
        explanation = result.get('change_explanation', '')
        expert_cred = result.get('expert_credibility', 0.5)

        print(f"  [{self.name}] Expert credibility assessed: {expert_cred:.0%}")
        print(f"  [{self.name}] {explanation}")

        if not warrants_change:
            print(f"  [{self.name}] Expert call does not warrant view change.")
            return view

        print(f"  [{self.name}] Updating view based on expert call insights...")

        # Validate and update
        validated_drivers = _validate_drivers(result.get('updated_drivers', {}), self.name, self.ticker)
        raw_rationale = result.get('updated_rationale', {})
        valid_drivers_set = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        validated_rationale = {k: v for k, v in raw_rationale.items() if k in valid_drivers_set}

        view.summary = result.get('updated_summary', view.summary)
        view.baseline_drivers = validated_drivers
        view.rationale = validated_rationale
        view.confidence = float(result.get('confidence', view.confidence))
        view.last_updated = datetime.now().isoformat()

        self._save_view(view)
        print(f"  [{self.name}] View updated and saved (confidence: {view.confidence:.0%})")

        return view

    # ───────────────────────────────────────────────────────────
    # SEC FILING LEARNING
    # ───────────────────────────────────────────────────────────

    def learn_from_sec_filing(self, filing_type: str, filing_data: dict) -> AnalystView:
        """
        Process SEC filing and potentially update view.

        SEC filings are AUTHORITATIVE but have lag (filed 45-60 days after period end).
        Weight: 10-K (highest) > 10-Q (moderate) > 8-K (event-specific)

        Args:
            filing_type: '10-K', '10-Q', or '8-K'
            filing_data: Dict with filing sections and metadata

        Returns:
            Updated AnalystView (may be unchanged if filing doesn't warrant update)
        """
        # Load current view
        view = self._load_view()
        if view is None:
            print(f"  [{self.name}] No existing view. Run ramp() first before processing SEC filings.")
            return None

        print(f"  [{self.name}] Processing SEC {filing_type} for {self.ticker}...")

        # Get ticker-specific drivers and periods
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(self.ticker, set())

        current_view_text = json.dumps({
            'summary': view.summary,
            'baseline_drivers': view.baseline_drivers,
            'rationale': view.rationale,
            'confidence': view.confidence,
        }, indent=2)

        # Extract key sections (truncate if too long)
        sections = filing_data.get('sections', {})
        risk_factors = sections.get('risk_factors', 'N/A')[:5000]
        mda = sections.get('mda', 'N/A')[:5000]
        business = sections.get('business', 'N/A')[:3000]

        filing_date = filing_data.get('filing_date', 'Unknown')
        report_date = filing_data.get('report_date', 'Unknown')

        prompt = f"""You are analyzing a SEC {filing_type} filing for {self.ticker}.

YOUR CURRENT VIEW ON {self.ticker}:
{current_view_text}

SEC FILING INFORMATION:
Filing Type: {filing_type}
Filing Date: {filing_date}
Period End: {report_date}

RISK FACTORS (Item 1A):
{risk_factors}

MD&A - MANAGEMENT'S DISCUSSION & ANALYSIS (Item 7):
{mda}

BUSINESS DESCRIPTION (Item 1):
{business}

IMPORTANT CONTEXT:
- SEC filings are AUTHORITATIVE sources but have 45-60 day lag after period end
- Weight filings by type:
  * 10-K = HIGHEST weight (annual comprehensive review, audited financials)
  * 10-Q = MODERATE weight (quarterly update, unaudited)
  * 8-K = LOWER weight (specific material events)
- Look for:
  * Revenue growth trends and forward guidance
  * Margin expansion/contraction drivers
  * New risk factors or changes to existing risks
  * Capital allocation plans (capex, R&D, buybacks)
  * Geographic/segment mix shifts
  * Competitive positioning changes
- ONLY update view if filing provides CONCRETE new information not already captured in your news-based view

Analyze this filing and decide:
1. Does this filing reveal NEW material insights about {self.ticker}'s financial outlook?
2. Should you adjust ANY driver assumptions based on management's discussion or risk factors?
3. How does this filing data compare to your existing news-based expectations?

Return a JSON object with:
- warrants_change: boolean (true only if filing provides material new insights)
- updated_drivers: the FULL driver map (only modify values where filing provides concrete data)
- updated_summary: revised summary if warranted
- updated_rationale: rationale for any CHANGED drivers
- confidence: float 0.0 to 1.0 (may increase given SEC filing is authoritative)
- change_explanation: 2-4 sentences on key insights from filing and their impact

Valid driver names: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}"""

        result = self.call_llm_json(prompt)

        warrants_change = result.get('warrants_change', False)
        explanation = result.get('change_explanation', '')

        print(f"  [{self.name}] {explanation}")

        if not warrants_change:
            print(f"  [{self.name}] SEC {filing_type} does not warrant view change.")
            return view

        print(f"  [{self.name}] Updating view based on SEC {filing_type}...")

        # Validate and update
        validated_drivers = _validate_drivers(result.get('updated_drivers', {}), self.name, self.ticker)
        raw_rationale = result.get('updated_rationale', {})
        valid_drivers_set = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        validated_rationale = {k: v for k, v in raw_rationale.items() if k in valid_drivers_set}

        view.summary = result.get('updated_summary', view.summary)
        view.baseline_drivers = validated_drivers
        view.rationale = validated_rationale
        view.confidence = float(result.get('confidence', view.confidence))
        view.last_updated = datetime.now().isoformat()

        # Track that we've processed this filing
        if not hasattr(view, 'sec_filings_processed'):
            view.sec_filings_processed = []
        view.sec_filings_processed.append({
            'type': filing_type,
            'filing_date': filing_date,
            'report_date': report_date,
            'processed_at': datetime.now().isoformat()
        })

        self._save_view(view)
        print(f"  [{self.name}] View updated based on {filing_type} (confidence: {view.confidence:.0%})")

        return view

    # ───────────────────────────────────────────────────────────
    # RAMP MODE — establish baseline view
    # ───────────────────────────────────────────────────────────

    def ramp(self, news_items: list = None) -> AnalystView:
        """Deep research pass: establish a full baseline view across all drivers/periods.
        Saves view to disk. Returns the AnalystView.
        """
        if news_items is None:
            news_items = self.gather_news()

        print(f"  [{self.name}] RAMP mode — establishing baseline view for {self.ticker} "
              f"({len(news_items)} news items)")

        news_text = self._format_news_for_prompt(news_items)

        company_info = config.COMPANIES.get(self.ticker, {})
        segments = company_info.get('segments', [])

        # Get ticker-specific drivers and periods
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(self.ticker, set())

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

Valid driver names: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}"""

        print(f"  [{self.name}] Calling LLM for baseline analysis...")
        result = self.call_llm_json(prompt)

        validated_drivers = _validate_drivers(result.get('baseline_drivers', {}), self.name, self.ticker)
        raw_rationale = result.get('rationale', {})
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        validated_rationale = {k: v for k, v in raw_rationale.items() if k in valid_drivers}

        view = AnalystView(
            ticker=self.ticker,
            summary=result.get('summary', ''),
            baseline_drivers=validated_drivers,
            rationale=validated_rationale,
            confidence=float(result.get('confidence', 0.0)),
            seen_headlines=[n.headline for n in news_items],
        )

        self._save_view(view)
        print(f"  [{self.name}] Baseline view saved "
              f"({len(validated_drivers)} drivers, confidence: {view.confidence:.0%})")
        return view

    # ───────────────────────────────────────────────────────────
    # Macro alert ingestion
    # ───────────────────────────────────────────────────────────

    def check_macro_alerts(self) -> list:
        """Load pending macro alerts for this ticker from disk. No LLM call."""
        try:
            from agents.macro_analyst_agent import MacroAnalystAgent
            macro = MacroAnalystAgent()
            return macro.get_pending_alerts(self.ticker)
        except Exception as e:
            print(f"  [{self.name}] Could not check macro alerts: {e}")
            return []

    def process_macro_alert(self, alert, view: AnalystView) -> AnalystView:
        """LLM decides if a macro alert warrants changing this company's view."""
        current_view_text = json.dumps({
            'summary': view.summary,
            'baseline_drivers': view.baseline_drivers,
            'confidence': view.confidence,
        }, indent=2)

        # Get ticker-specific drivers and periods
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(self.ticker, set())

        prompt = f"""A macro alert has been issued that may affect {self.ticker}.

MACRO ALERT:
  Severity: {alert.severity}
  Headline: {alert.headline}
  Description: {alert.description}
  Affected indicators: {', '.join(alert.affected_indicators)}
  Suggested driver impacts: {json.dumps(alert.suggested_driver_impacts, indent=2)}

YOUR CURRENT VIEW ON {self.ticker}:
{current_view_text}

Does this macro alert warrant changing any of your driver assumptions for {self.ticker}?
Consider: the macro analyst's suggested impacts are suggestions — use your company-specific
knowledge to decide if and how much to adjust.

Return a JSON object with:
- warrants_change: boolean
- updated_drivers: the FULL driver map (only modify values where the macro alert is relevant)
- updated_summary: revised summary incorporating macro context
- confidence: float 0.0 to 1.0
- explanation: 1-2 sentences on your decision

Valid driver names: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}"""

        result = self.call_llm_json(prompt)

        if not result.get('warrants_change', False):
            print(f"  [{self.name}] Macro alert does not warrant view change: "
                  f"{result.get('explanation', '')}")
            return view

        print(f"  [{self.name}] Updating view based on macro alert: "
              f"{result.get('explanation', '')}")
        validated_drivers = _validate_drivers(result.get('updated_drivers', {}), self.name, self.ticker)
        if validated_drivers:
            view.baseline_drivers = validated_drivers
        view.summary = result.get('updated_summary', view.summary)
        view.confidence = float(result.get('confidence', view.confidence))
        view.last_updated = datetime.now().isoformat()
        self._save_view(view)

        # Acknowledge the alert
        try:
            from agents.macro_analyst_agent import MacroAnalystAgent
            macro = MacroAnalystAgent()
            macro.acknowledge_alert(alert.id, result.get('explanation', 'processed'))
        except Exception:
            pass

        return view

    # ───────────────────────────────────────────────────────────
    # MONITOR MODE — check for material updates
    # ───────────────────────────────────────────────────────────

    def monitor(self, news_items: list = None) -> AnalystView:
        """Check for new news since last run. Only calls LLM if new material exists.
        Also checks for macro alerts and latest briefing context.
        Returns the (possibly updated) AnalystView.
        """
        view = self._load_view()
        if view is None:
            print(f"  [{self.name}] No existing view — falling back to ramp")
            return self.ramp(news_items)

        # Check for macro alerts
        macro_alerts = self.check_macro_alerts()
        if macro_alerts:
            print(f"  [{self.name}] {len(macro_alerts)} pending macro alert(s) for {self.ticker}")
            for alert in macro_alerts:
                view = self.process_macro_alert(alert, view)

        if news_items is None:
            news_items = self.gather_news()

        # Find headlines we haven't seen before
        seen = set(view.seen_headlines)
        new_items = [n for n in news_items if n.headline not in seen]

        if not new_items:
            print(f"  [{self.name}] MONITOR — no new headlines, view unchanged")
            return view

        print(f"  [{self.name}] MONITOR — {len(new_items)} new headline(s) found, calling LLM...")

        new_news_text = self._format_news_for_prompt(new_items)
        current_view_text = json.dumps({
            'summary': view.summary,
            'baseline_drivers': view.baseline_drivers,
            'rationale': view.rationale,
            'confidence': view.confidence,
        }, indent=2)

        # Include macro briefing context if available
        macro_context = ""
        try:
            from agents.macro_analyst_agent import MacroAnalystAgent
            macro = MacroAnalystAgent()
            briefing = macro.get_latest_briefing()
            if briefing:
                company_note = briefing.company_notes.get(self.ticker, '')
                if company_note:
                    macro_context = f"\n\nMACRO CONTEXT (from latest briefing):\nOutlook: {briefing.outlook}\n{self.ticker} note: {company_note}"
        except Exception:
            pass

        # Get ticker-specific drivers and periods
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(self.ticker, set())

        prompt = f"""You are monitoring {self.ticker}. You have an existing baseline view and new news has come in.

YOUR CURRENT VIEW:
{current_view_text}

NEW NEWS (not seen before):{new_news_text}
{macro_context}

Decide: does any of this new news MATERIALLY change your view on any driver?
Material = would move a driver value by a meaningful amount, not noise.

Return a JSON object with:
- material_change: boolean — true if your view should be updated, false if this is noise
- updated_summary: your revised summary (or repeat the old one if no change)
- updated_drivers: the FULL driver map (existing values + any changes). Only change values where the news warrants it.
- updated_rationale: rationale for any CHANGED drivers (keep existing rationale for unchanged)
- confidence: float 0.0 to 1.0
- change_explanation: 1-2 sentences on what changed and why (or "No material change")

Valid driver names: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}"""

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

        validated_drivers = _validate_drivers(result.get('updated_drivers', {}), self.name, self.ticker)
        raw_rationale = result.get('updated_rationale', {})
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        validated_rationale = {k: v for k, v in raw_rationale.items() if k in valid_drivers}

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
            print(f"  [{self.name}] Gathering news for {self.ticker}...")
            news_items = self.gather_news()
            if not news_items:
                print(f"  [{self.name}] No news found for {self.ticker}")
                if self.has_view:
                    print(f"  [{self.name}] Returning cached view")
                    return self._load_view().to_driver_update_package()
                return DriverUpdatePackage.empty(self.ticker)

            mode = "MONITOR" if self.has_view else "RAMP"
            print(f"  [{self.name}] Auto-detected mode: {mode} "
                  f"({len(news_items)} news items)")

            if self.has_view:
                view = self.monitor(news_items)
            else:
                view = self.ramp(news_items)

            return view.to_driver_update_package()
        except Exception as e:
            print(f"  [{self.name}] Error producing driver update: {e}")
            return DriverUpdatePackage.empty(self.ticker)

    # ───────────────────────────────────────────────────────────
    # PM "Request Update" challenge/response
    # ───────────────────────────────────────────────────────────

    def respond_to_challenge(self, challenge_question: str,
                              target_drivers: list,
                              view: AnalystView) -> dict:
        """Respond to a PM challenge question about specific driver assumptions.
        Returns dict with: response, revised_drivers, confidence_after, concedes.
        """
        # Build targeted driver context
        targeted_values = {}
        targeted_rationale = {}
        for drv in target_drivers:
            if drv in view.baseline_drivers:
                targeted_values[drv] = view.baseline_drivers[drv]
            if drv in (view.rationale or {}):
                targeted_rationale[drv] = view.rationale[drv]

        driver_text = json.dumps(targeted_values, indent=2)
        rationale_text = json.dumps(targeted_rationale, indent=2)

        # Include recent news context
        news_context = ""
        if self._cached_news:
            headlines = [f"- [{n.source}] {n.headline}" for n in self._cached_news[:8]]
            news_context = "\n\nRecent news context:\n" + "\n".join(headlines)

        # Get ticker-specific drivers and periods
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(self.ticker, set())

        prompt = f"""The Portfolio Manager is challenging your assumptions on {self.ticker}.

PM'S CHALLENGE:
{challenge_question}

YOUR CURRENT DRIVER VALUES (targeted):
{driver_text}

YOUR RATIONALE:
{rationale_text}

YOUR OVERALL VIEW:
Summary: {view.summary}
Confidence: {view.confidence:.0%}
{news_context}

Respond to the PM's challenge. You may:
1. DEFEND your position with additional evidence/reasoning
2. CONCEDE if the PM raises a valid point, and revise your driver values

Return a JSON object with:
- response: 2-4 sentence defense or concession
- revised_drivers: object mapping driver_name -> {{period: value}} — only include drivers you are REVISING (empty object if defending unchanged)
- confidence_after: float 0.0 to 1.0 (your confidence after considering the challenge)
- concedes: boolean — true if you are revising any values based on the challenge

Valid driver names: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}"""

        result = self.call_llm_json(prompt)

        # Validate any revised drivers
        revised = _validate_drivers(result.get('revised_drivers', {}), self.name, self.ticker)

        return {
            'response': result.get('response', ''),
            'revised_drivers': revised,
            'confidence_after': float(result.get('confidence_after', view.confidence)),
            'concedes': bool(result.get('concedes', False)),
        }

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
