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
from pathlib import Path

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
    'TSM': {
        'smartphone_growth', 'hpc_growth', 'iot_growth',
        'automotive_growth', 'digital_consumer_growth',
        'gm_improvement_bps', 'opex_improvement_bps', 'tax_rate_bps',
    },
    'ASML': {
        'euv_growth', 'arfi_growth', 'arf_growth', 'krf_growth', 'others_growth',
        'gm_improvement_bps',
    },
    'CRWV': {
        'revenue_growth',
        'ebitda_margin_improvement_bps', 'opex_improvement_bps', 'tax_rate_bps',
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
    'TSM': {
        'FY2027', 'FY2028', 'FY2029',
    },
    'ASML': {
        'FY2027', 'FY2028', 'FY2029',
    },
    'CRWV': {
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

    # ───────────────────────────────────────────────────────────
    # CONSENSUS UNDERSTANDING
    # ───────────────────────────────────────────────────────────

    def understand_consensus(self) -> dict:
        """
        Read consensus estimates and compare to own model assumptions.

        Returns:
            {
                'consensus': {...},  # Raw consensus data
                'own_model': {...},  # Own model forecasts
                'differences': {...}, # Key differences
                'summary': str,      # Text summary of differences
            }
        """
        from tools.consensus_reader import ConsensusReader

        print(f"  [{self.ticker}] Reading consensus estimates...")

        try:
            reader = ConsensusReader(self.ticker)
            consensus_data = reader.get_annual_consensus(['FY2026', 'FY2027', 'FY2028'])
        except FileNotFoundError as e:
            print(f"  [{self.ticker}] Warning: {e}")
            return {
                'consensus': None,
                'own_model': None,
                'differences': {},
                'summary': f"No consensus estimates available for {self.ticker}",
            }

        # Load own model forecasts
        own_model = self._get_own_model_forecasts()

        # Compare
        differences = self._compare_to_consensus(consensus_data, own_model)

        # Generate summary
        summary = self._summarize_consensus_differences(differences)

        result = {
            'consensus': consensus_data,
            'own_model': own_model,
            'differences': differences,
            'summary': summary,
        }

        print(f"  [{self.ticker}] Consensus analysis complete")
        return result

    def _get_own_model_forecasts(self) -> dict:
        """Extract own model forecasts from DCF engine or model file."""
        company_info = config.COMPANIES.get(self.ticker, {})

        # Check if company has a DCF engine
        if not company_info.get('has_full_model'):
            return {}

        excel_path = company_info.get('excel_path')
        if not excel_path or not Path(excel_path).exists():
            return {}

        # Load via DCF engine to get consistent forecast
        engine_class_name = company_info.get('engine_class')
        if not engine_class_name:
            return {}

        try:
            # Import the appropriate engine
            if engine_class_name == 'NVDADCFEngine':
                from models.pm_agent_interface import NVDADCFEngine as EngineClass
            elif engine_class_name == 'CDNSDCFEngine':
                from models.cdns_engine import CDNSDCFEngine as EngineClass
            elif engine_class_name == 'CoreWeaveDCFEngine':
                from models.crwv_engine import CoreWeaveDCFEngine as EngineClass
            elif engine_class_name == 'TSMCDCFEngine':
                from models.tsm_engine import TSMCDCFEngine as EngineClass
            elif engine_class_name == 'ASMLDCFEngine':
                from models.asml_engine import ASMLDCFEngine as EngineClass
            else:
                return {}

            # Load engine and compute baseline
            engine = EngineClass(excel_path)
            result = engine.compute_dcf()

            # Extract key metrics
            forecast = {
                'FY2026': {},
                'FY2027': {},
                'FY2028': {},
            }

            # Map engine output to standardized format
            proj_years = ['FY2026', 'FY2027', 'FY2028']
            for fy in proj_years:
                if fy in result.get('total_rev', {}):
                    forecast[fy]['revenue'] = result['total_rev'][fy]
                if fy in result.get('ebit', {}):
                    forecast[fy]['operating_income'] = result['ebit'][fy]
                if fy in result.get('ebit_margin', {}):
                    forecast[fy]['operating_margin'] = result['ebit_margin'][fy]

                # Segment revenues if available
                if 'seg_rev' in result:
                    forecast[fy]['segments'] = {}
                    for seg, seg_data in result['seg_rev'].items():
                        if fy in seg_data:
                            forecast[fy]['segments'][seg] = seg_data[fy]

            return forecast

        except Exception as e:
            print(f"  [{self.ticker}] Warning: Could not load own model: {e}")
            return {}

    def _compare_to_consensus(self, consensus: dict, own_model: dict) -> dict:
        """Compare own model to consensus and identify key differences."""
        if not consensus or not own_model:
            return {}

        differences = {}
        fiscal_years = ['FY2026', 'FY2027', 'FY2028']

        for fy in fiscal_years:
            if fy not in own_model:
                continue

            fy_diff = {}

            # Revenue comparison
            cons_rev = consensus['revenue'].get(fy)
            own_rev = own_model[fy].get('revenue')

            if cons_rev and own_rev:
                diff_pct = (own_rev / cons_rev - 1)
                fy_diff['revenue'] = {
                    'consensus': cons_rev,
                    'own': own_rev,
                    'diff_pct': diff_pct,
                    'direction': 'above' if diff_pct > 0 else 'below',
                    'material': abs(diff_pct) > 0.05,  # >5% difference is material
                }

            # Operating income comparison
            cons_oi = consensus['margins'].get('operating_income', {}).get(fy)
            own_oi = own_model[fy].get('operating_income')

            if cons_oi and own_oi:
                diff_pct = (own_oi / cons_oi - 1)
                fy_diff['operating_income'] = {
                    'consensus': cons_oi,
                    'own': own_oi,
                    'diff_pct': diff_pct,
                    'direction': 'above' if diff_pct > 0 else 'below',
                    'material': abs(diff_pct) > 0.05,
                }

            # Operating margin comparison (derived)
            if cons_rev and cons_oi and own_rev and own_oi:
                cons_margin = cons_oi / cons_rev
                own_margin = own_oi / own_rev
                diff_bps = (own_margin - cons_margin) * 10000

                fy_diff['operating_margin'] = {
                    'consensus': cons_margin,
                    'own': own_margin,
                    'diff_bps': diff_bps,
                    'direction': 'above' if diff_bps > 0 else 'below',
                    'material': abs(diff_bps) > 100,  # >100bps is material
                }

            # Segment comparisons if available
            if 'segments' in own_model[fy] and consensus['segments']:
                fy_diff['segments'] = {}

                for seg_key, cons_seg_data in consensus['segments'].items():
                    cons_seg_rev = cons_seg_data.get(fy)
                    own_seg_rev = own_model[fy]['segments'].get(seg_key)

                    if cons_seg_rev and own_seg_rev:
                        diff_pct = (own_seg_rev / cons_seg_rev - 1)
                        fy_diff['segments'][seg_key] = {
                            'consensus': cons_seg_rev,
                            'own': own_seg_rev,
                            'diff_pct': diff_pct,
                            'direction': 'above' if diff_pct > 0 else 'below',
                            'material': abs(diff_pct) > 0.10,  # >10% for segments
                        }

            if fy_diff:
                differences[fy] = fy_diff

        return differences

    def _summarize_consensus_differences(self, differences: dict) -> str:
        """Generate a text summary of key consensus differences."""
        if not differences:
            return "No material differences vs consensus identified."

        summary_lines = [f"Consensus Comparison for {self.ticker}"]
        summary_lines.append("=" * 60)

        for fy in sorted(differences.keys()):
            fy_diff = differences[fy]
            summary_lines.append(f"\n{fy}:")

            # Revenue
            if 'revenue' in fy_diff and fy_diff['revenue']['material']:
                d = fy_diff['revenue']
                summary_lines.append(
                    f"  Revenue: {d['direction'].upper()} consensus by {d['diff_pct']:.1%} "
                    f"(${d['own']:,.0f}M vs ${d['consensus']:,.0f}M)"
                )

            # Operating income
            if 'operating_income' in fy_diff and fy_diff['operating_income']['material']:
                d = fy_diff['operating_income']
                summary_lines.append(
                    f"  Op Income: {d['direction'].upper()} consensus by {d['diff_pct']:.1%} "
                    f"(${d['own']:,.0f}M vs ${d['consensus']:,.0f}M)"
                )

            # Operating margin
            if 'operating_margin' in fy_diff and fy_diff['operating_margin']['material']:
                d = fy_diff['operating_margin']
                summary_lines.append(
                    f"  Op Margin: {d['direction'].upper()} consensus by {d['diff_bps']:.0f}bps "
                    f"({d['own']:.1%} vs {d['consensus']:.1%})"
                )

            # Segments with material differences
            if 'segments' in fy_diff:
                material_segs = [seg for seg, data in fy_diff['segments'].items()
                                if data.get('material')]
                if material_segs:
                    summary_lines.append(f"  Material segment differences: {', '.join(material_segs)}")

        return "\n".join(summary_lines)

    # ───────────────────────────────────────────────────────────
    # THESIS DEVELOPMENT MODE
    # ───────────────────────────────────────────────────────────

    def develop_thesis(self, mode: str = 'contrarian') -> dict:
        """
        Develop 1-3 differentiated thesis points that would make view more bullish/bearish
        than consensus. For each thesis point, conduct supporting analyses and quantify
        into DCF driver changes.

        Args:
            mode: 'contrarian' (find differences vs consensus) or 'deep_dive' (explore key drivers)

        Returns:
            {
                'timestamp': str,
                'ticker': str,
                'thesis_points': [
                    {
                        'thesis': str,
                        'direction': 'bullish'|'bearish',
                        'conviction': float (0-1),
                        'analyses': [
                            {
                                'analysis_type': str,
                                'question': str,
                                'evidence': str,
                                'source': str,
                                'finding': str,
                            },
                        ],
                        'driver_implications': {
                            'datacenter_growth': {'FY2028': 0.42, 'rationale': '...'},
                            ...
                        },
                        'confidence': float (0-1),
                    },
                ],
                'summary': str,
            }
        """
        print(f"\n  [{self.name}] Developing thesis for {self.ticker}...")
        print(f"    Mode: {mode}")

        # Step 0: Understand consensus
        consensus_comparison = self.understand_consensus()

        # Step 1: Identify potential thesis points
        thesis_points = self._identify_thesis_points(mode, consensus_comparison)

        # Step 2: For each thesis point, conduct supporting analyses
        for thesis_point in thesis_points:
            print(f"\n    Thesis: {thesis_point['thesis']}")
            analyses = self._conduct_supporting_analyses(thesis_point)
            thesis_point['analyses'] = analyses

            # Step 3: Quantify into DCF drivers
            driver_implications = self._quantify_thesis_to_drivers(thesis_point)
            thesis_point['driver_implications'] = driver_implications

        # Step 4: Build summary
        summary = self._summarize_thesis(thesis_points)

        result = {
            'timestamp': datetime.now().isoformat(),
            'ticker': self.ticker,
            'mode': mode,
            'thesis_points': thesis_points,
            'summary': summary,
        }

        # Save thesis
        self._save_thesis(result)

        return result

    def _identify_thesis_points(self, mode: str, consensus_comparison: dict = None) -> List[dict]:
        """Identify 1-3 differentiated thesis points using LLM."""

        # Get context from specialist input
        specialist_context = ""
        try:
            specialist_input = self.seek_specialist_input()
            specialist_context = f"\nSpecialist findings:\n{specialist_input['narrative']}"
        except:
            pass

        # Get market valuation context
        valuation_context = ""
        try:
            valuation = self.check_market_valuation()
            valuation_context = f"\nMarket valuation: {valuation['assessment']}\n{valuation['implications']}"
        except:
            pass

        # Add consensus context
        consensus_context = ""
        if consensus_comparison and consensus_comparison.get('summary'):
            consensus_context = f"\nConsensus comparison:\n{consensus_comparison['summary']}"

        prompt = f"""You are developing an investment thesis for {self.ticker}.

Mode: {mode}
{'Focus on finding points where your view differs from consensus.' if mode == 'contrarian' else 'Focus on deep-diving into key value drivers.'}

Context:
{specialist_context}
{valuation_context}
{consensus_context}

Identify 1-3 fundamental thesis points that would drive differentiated views on {self.ticker}.

For each thesis point, specify:
1. Clear thesis statement (one sentence)
2. Direction: bullish or bearish
3. Why this differs from consensus (what is consensus missing?)
4. Initial conviction level (0.0-1.0)
5. Key questions to answer to validate this thesis

Return JSON with:
{{
  "thesis_points": [
    {{
      "thesis": "Clear statement of thesis",
      "direction": "bullish" or "bearish",
      "consensus_view": "What consensus believes",
      "our_view": "What we believe and why",
      "conviction": 0.7,
      "key_questions": ["Question 1", "Question 2", "Question 3"],
    }},
    ...
  ]
}}

Focus on theses that are:
- Material to valuation (not noise)
- Testable with available data/evidence
- Specific enough to quantify into DCF drivers"""

        try:
            data = self.call_llm_json(prompt)
            return data.get('thesis_points', [])
        except Exception as e:
            print(f"      ⚠️  Could not identify thesis points: {e}")
            return []

    def _conduct_supporting_analyses(self, thesis_point: dict) -> List[dict]:
        """Conduct 1-3 analyses to support/refute the thesis point."""

        key_questions = thesis_point.get('key_questions', [])
        analyses = []

        print(f"      Conducting {len(key_questions[:3])} supporting analyses...")

        for i, question in enumerate(key_questions[:3], 1):
            print(f"        Analysis {i}: {question[:60]}...")

            # Determine analysis type and gather evidence
            analysis = self._gather_evidence_for_question(question, thesis_point)
            analyses.append(analysis)

        return analyses

    def _gather_evidence_for_question(self, question: str, thesis_point: dict) -> dict:
        """Gather evidence to answer a specific question."""

        # Try multiple evidence sources
        evidence_pieces = []

        # 1. Check news
        try:
            news_items = self.gather_news()
            if news_items:
                relevant_news = [n for n in news_items[:5] if any(
                    keyword in n.headline.lower()
                    for keyword in ['ai', 'datacenter', 'gpu', 'growth', 'margin', 'competition']
                )]
                if relevant_news:
                    evidence_pieces.append({
                        'source': 'company_news',
                        'data': [n.headline for n in relevant_news[:3]],
                    })
        except:
            pass

        # 2. Check specialist views
        try:
            specialist_input = self.seek_specialist_input()
            relevant_findings = [
                f for f in specialist_input['key_findings']
                if f['materiality'] in ['high', 'medium']
            ]
            if relevant_findings:
                evidence_pieces.append({
                    'source': 'specialist_agents',
                    'data': [f['finding'] for f in relevant_findings],
                })
        except:
            pass

        # 3. Synthesize evidence into finding
        evidence_summary = "\n".join([
            f"From {e['source']}: " + "; ".join(e['data'])
            for e in evidence_pieces
        ])

        prompt = f"""You are analyzing evidence for an investment thesis.

Thesis: {thesis_point['thesis']}
Direction: {thesis_point['direction']}

Question to answer: {question}

Evidence gathered:
{evidence_summary if evidence_summary else '(Limited evidence available - use industry knowledge)'}

Based on this evidence, provide:
1. Analysis type (e.g., "competitive analysis", "demand analysis", "margin analysis")
2. Key finding (what does the evidence suggest?)
3. Confidence in finding (0.0-1.0)
4. Supporting rationale

Return JSON:
{{
  "analysis_type": "...",
  "finding": "Clear statement of what evidence suggests",
  "confidence": 0.7,
  "rationale": "Why this evidence supports/refutes the thesis",
}}"""

        try:
            data = self.call_llm_json(prompt)
            return {
                'analysis_type': data.get('analysis_type', 'general'),
                'question': question,
                'evidence': evidence_summary if evidence_summary else 'Industry knowledge and specialist input',
                'finding': data.get('finding', 'Insufficient evidence'),
                'confidence': data.get('confidence', 0.5),
                'rationale': data.get('rationale', ''),
            }
        except Exception as e:
            return {
                'analysis_type': 'general',
                'question': question,
                'evidence': evidence_summary,
                'finding': f'Analysis incomplete: {e}',
                'confidence': 0.3,
                'rationale': '',
            }

    def _quantify_thesis_to_drivers(self, thesis_point: dict) -> dict:
        """Quantify thesis point into specific DCF driver changes."""

        # Get valid drivers for this ticker
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(self.ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(self.ticker, set())

        # Build context from analyses
        analyses_summary = "\n".join([
            f"- {a['finding']} (confidence: {a['confidence']:.0%})"
            for a in thesis_point.get('analyses', [])
        ])

        prompt = f"""You are quantifying an investment thesis into DCF driver changes.

Ticker: {self.ticker}
Thesis: {thesis_point['thesis']}
Direction: {thesis_point['direction']}

Supporting analyses:
{analyses_summary}

Available DCF drivers: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}

Based on the thesis and supporting evidence, quantify specific changes to DCF drivers.

For each driver you want to change:
1. Identify which driver(s) are affected
2. Specify magnitude of change (e.g., datacenter_growth from 0.35 to 0.42)
3. Provide clear rationale linking thesis → evidence → driver change

Return JSON:
{{
  "driver_changes": {{
    "datacenter_growth": {{
      "FY2028": 0.42,
      "baseline": 0.35,
      "change": "+7pp",
      "rationale": "Why this driver should change based on thesis"
    }},
    ...
  }},
  "conviction": 0.7,
  "sensitivity": "High/Medium/Low - how sensitive is valuation to this thesis"
}}

Only include drivers that are materially impacted by this thesis.
Be conservative - only change drivers where you have strong evidence."""

        try:
            data = self.call_llm_json(prompt)
            driver_changes = data.get('driver_changes', {})

            # Validate and clean driver changes
            validated_changes = {}
            for driver, change_data in driver_changes.items():
                if driver in valid_drivers:
                    validated_changes[driver] = change_data

            return {
                'driver_changes': validated_changes,
                'conviction': data.get('conviction', thesis_point.get('conviction', 0.5)),
                'sensitivity': data.get('sensitivity', 'Medium'),
            }
        except Exception as e:
            print(f"        ⚠️  Could not quantify to drivers: {e}")
            return {
                'driver_changes': {},
                'conviction': 0.3,
                'sensitivity': 'Unknown',
            }

    def _summarize_thesis(self, thesis_points: List[dict]) -> str:
        """Generate executive summary of thesis."""

        bullish_points = [t for t in thesis_points if t['direction'] == 'bullish']
        bearish_points = [t for t in thesis_points if t['direction'] == 'bearish']

        lines = [f"Investment Thesis for {self.ticker}"]
        lines.append("=" * 60)

        if bullish_points:
            lines.append(f"\nBULLISH POINTS ({len(bullish_points)}):")
            for i, point in enumerate(bullish_points, 1):
                lines.append(f"  {i}. {point['thesis']}")
                lines.append(f"     Conviction: {point.get('conviction', 0.5):.0%}")
                if point.get('driver_implications', {}).get('driver_changes'):
                    lines.append(f"     Drivers: {', '.join(point['driver_implications']['driver_changes'].keys())}")

        if bearish_points:
            lines.append(f"\nBEARISH POINTS ({len(bearish_points)}):")
            for i, point in enumerate(bearish_points, 1):
                lines.append(f"  {i}. {point['thesis']}")
                lines.append(f"     Conviction: {point.get('conviction', 0.5):.0%}")
                if point.get('driver_implications', {}).get('driver_changes'):
                    lines.append(f"     Drivers: {', '.join(point['driver_implications']['driver_changes'].keys())}")

        return "\n".join(lines)

    def _save_thesis(self, thesis: dict):
        """Save thesis to file."""
        thesis_file = config.ANALYST_VIEWS_DIR / f"{self.ticker}_thesis.json"
        try:
            with open(thesis_file, 'w') as f:
                json.dump(thesis, f, indent=2)
            print(f"\n  ✅ Thesis saved to {thesis_file}")
        except Exception as e:
            print(f"  ⚠️  Could not save thesis: {e}")

    # ───────────────────────────────────────────────────────────
    # MARKET VALUATION CHECK
    # ───────────────────────────────────────────────────────────

    def check_market_valuation(self) -> dict:
        """
        Check with market monitor about current trading multiples and valuation.

        Gets:
        - Current market multiples (P/E NTM, P/E TTM, EV/EBITDA)
        - Fair multiples from framework
        - Assessment: UNDERVALUED/FAIRLY VALUED/OVERVALUED
        - Implications for DCF assumptions

        Returns:
            {
                'timestamp': str,
                'current_multiples': {
                    'pe_ntm': float,
                    'pe_ttm': float,
                    'price': float,
                },
                'fair_multiples': {
                    'pe_ntm': float,
                    'range': str,
                },
                'assessment': str,
                'premium_discount': float,
                'implications': str,
            }
        """
        print(f"\n  [{self.name}] Checking market valuation for {self.ticker}...")

        result = {
            'timestamp': datetime.now().isoformat(),
            'ticker': self.ticker,
            'current_multiples': {},
            'fair_multiples': {},
            'assessment': '',
            'premium_discount': 0,
            'implications': '',
        }

        try:
            from tools.market_monitor import MarketMonitor
            from tools.multiples_framework import MultiplesFramework

            # Get current market data
            monitor = MarketMonitor()
            snapshot = monitor.get_market_snapshot()

            if self.ticker in snapshot.get('stocks', {}):
                stock_data = snapshot['stocks'][self.ticker]

                result['current_multiples'] = {
                    'pe_ntm': stock_data.get('pe_forward_ntm'),
                    'pe_ttm': stock_data.get('pe_trailing_ttm'),
                    'price': stock_data.get('price'),
                    'market_cap': stock_data.get('market_cap'),
                }

            # Get fair multiples from framework
            framework = MultiplesFramework()
            if not framework.framework_file.exists():
                print("    No framework found, developing new one...")
                framework.develop_view()

            fair = framework.get_fair_multiple(self.ticker, 'forward_pe')
            if fair:
                result['fair_multiples'] = {
                    'pe_ntm': fair['point_estimate'],
                    'range': f"{fair['range_low']:.1f}x - {fair['range_high']:.1f}x",
                    'range_low': fair['range_low'],
                    'range_high': fair['range_high'],
                }

            # Compare to framework
            current_pe = result['current_multiples'].get('pe_ntm')
            fair_pe = result['fair_multiples'].get('pe_ntm')

            if current_pe and fair_pe:
                comparison = framework.compare_to_market(self.ticker, current_pe)

                result['assessment'] = comparison['assessment']
                result['premium_discount'] = comparison['premium_discount']

                # Generate implications for DCF
                implications = []

                if comparison['premium_discount'] < -0.20:
                    implications.append(
                        f"Market is pricing in {abs(comparison['premium_discount']):.0%} discount to fair value. "
                        "This suggests either: (1) Market expects earnings below consensus, "
                        "(2) Market sees execution risk or competitive threats, "
                        "(3) Sector rotation away from growth stocks."
                    )
                    implications.append(
                        "DCF implication: Consider stress-testing downside scenarios with lower growth or margin compression."
                    )

                elif comparison['premium_discount'] > 0.20:
                    implications.append(
                        f"Market is pricing in {comparison['premium_discount']:.0%} premium to fair value. "
                        "This suggests either: (1) Market expects earnings above consensus, "
                        "(2) Strong momentum/sentiment driving multiples higher, "
                        "(3) Scarcity premium for AI exposure."
                    )
                    implications.append(
                        "DCF implication: Market expectations may be ahead of fundamentals - ensure DCF growth assumptions are achievable."
                    )

                else:
                    implications.append(
                        f"Market valuation is within fair range (premium/discount: {comparison['premium_discount']:+.1%}). "
                        "Current multiples align with fundamental drivers."
                    )
                    implications.append(
                        "DCF implication: Current DCF assumptions likely aligned with market consensus."
                    )

                result['implications'] = '\n'.join(implications)

        except Exception as e:
            result['assessment'] = f"Could not complete market check: {e}"
            print(f"    ⚠️  Error: {e}")

        return result

    # ───────────────────────────────────────────────────────────
    # MULTIPLES-BASED VALUATION
    # ───────────────────────────────────────────────────────────

    def analyze_multiples_perspective(self, current_price: float = None) -> dict:
        """
        Analyze valuation from multiples perspective (P/E, EV/EBITDA).
        Provides sanity check against DCF and identifies cheap/expensive relativities.

        Returns:
            {
                'timestamp': str,
                'current_price': float,
                'pe_valuations': {
                    'TTM': {'multiple': x, 'earnings': y, 'implied_price': z, 'upside': u},
                    ...
                },
                'ev_ebitda_valuations': {...},
                'summary': {
                    'ntm_pe_implied': float,
                    'ntm_ev_ebitda_implied': float,
                    'average_implied': float,
                    'average_upside': float,
                },
                'assessment': str,
            }
        """
        print(f"\n  [{self.name}] Analyzing multiples perspective for {self.ticker}...")

        # Try to load multiples engine if it exists
        result = {
            'timestamp': datetime.now().isoformat(),
            'ticker': self.ticker,
            'method': 'multiples',
            'current_price': current_price,
            'pe_valuations': {},
            'ev_ebitda_valuations': {},
            'summary': {},
            'assessment': '',
        }

        try:
            # Try NVDA multiples engine
            if self.ticker == 'NVDA':
                from models.nvda_multiples_engine import NVDAMultiplesEngine
                engine = NVDAMultiplesEngine(config.COMPANIES['NVDA']['excel_path'])
                multiples_result = engine.compute_multiples_valuation(current_price=current_price or 184.97)

                result['pe_valuations'] = multiples_result['pe_valuations']
                result['ev_ebitda_valuations'] = multiples_result['ev_ebitda_valuations']
                result['summary'] = multiples_result['summary']

                # Assessment
                avg_upside = multiples_result['summary']['average_upside']
                if avg_upside > 0.20:
                    result['assessment'] = f"UNDERVALUED: Multiples suggest {avg_upside:+.1%} upside"
                elif avg_upside < -0.10:
                    result['assessment'] = f"OVERVALUED: Multiples suggest {avg_upside:+.1%} downside"
                else:
                    result['assessment'] = f"FAIRLY VALUED: Multiples suggest {avg_upside:+.1%} upside"

        except Exception as e:
            print(f"    ⚠️  Could not load multiples engine: {e}")
            result['assessment'] = f"Multiples analysis unavailable: {e}"

        return result

    def debate_multiples_vs_dcf(self, dcf_result: dict, current_price: float = None) -> dict:
        """
        Compare DCF valuation vs multiples-based valuation.
        Identifies divergences and flags if one method suggests material opportunity.

        Args:
            dcf_result: Result from DCF engine (contains 'implied_price')
            current_price: Current stock price

        Returns:
            {
                'dcf_implied': float,
                'multiples_implied': float,
                'divergence': float (difference in implied prices),
                'analysis': str,
                'consensus_view': str,
            }
        """
        print(f"\n  [{self.name}] Comparing DCF vs Multiples for {self.ticker}...")

        multiples_result = self.analyze_multiples_perspective(current_price=current_price)

        dcf_implied = dcf_result.get('implied_price', 0) if isinstance(dcf_result, dict) else 0
        multiples_implied = multiples_result['summary'].get('average_implied', 0)
        current = current_price or 184.97

        comparison = {
            'timestamp': datetime.now().isoformat(),
            'current_price': current,
            'dcf_implied': dcf_implied,
            'multiples_implied': multiples_implied,
            'divergence': multiples_implied - dcf_implied if dcf_implied > 0 else 0,
            'divergence_pct': (multiples_implied / dcf_implied - 1) if dcf_implied > 0 else 0,
        }

        # Build analysis
        analysis_lines = []
        if abs(comparison['divergence_pct']) < 0.10:
            analysis_lines.append("✓ Methods ALIGNED — DCF and multiples suggest similar valuations")
        elif comparison['divergence_pct'] > 0.10:
            analysis_lines.append(f"⚠️  DIVERGENCE — Multiples suggest {comparison['divergence_pct']:+.1%} MORE upside than DCF")
            analysis_lines.append(f"   Possible reasons: (1) DCF too conservative on growth, (2) Multiples inflated")
        else:
            analysis_lines.append(f"⚠️  DIVERGENCE — DCF suggests {abs(comparison['divergence_pct']):+.1%} MORE upside than multiples")
            analysis_lines.append(f"   Possible reasons: (1) DCF too aggressive on growth, (2) Multiples compressed")

        # Consensus
        avg_view = (dcf_implied + multiples_implied) / 2
        consensus_upside = (avg_view / current - 1) if current > 0 else 0

        analysis_lines.append(f"\nCONSENSUS VIEW:")
        analysis_lines.append(f"  DCF implies:      ${dcf_implied:.2f} ({(dcf_implied/current-1):+.1%})")
        analysis_lines.append(f"  Multiples imply:  ${multiples_implied:.2f} ({(multiples_implied/current-1):+.1%})")
        analysis_lines.append(f"  Blended target:   ${avg_view:.2f} ({consensus_upside:+.1%})")

        comparison['analysis'] = '\n'.join(analysis_lines)
        comparison['consensus_view'] = f"Target: ${avg_view:.2f} ({consensus_upside:+.1%} upside)"

        return comparison

    # ───────────────────────────────────────────────────────────
    # SPECIALIST INPUT SYNTHESIS
    # ───────────────────────────────────────────────────────────

    def seek_specialist_input(self) -> dict:
        """
        Query all specialist agents, synthesize their insights, and recommend
        DCF driver updates based on what is new and material.

        Returns:
            {
                'timestamp': str,
                'specialist_views': {
                    'macro': {...},
                    'commodities': {...},
                    'market': {...},
                },
                'key_findings': [
                    {
                        'source': 'macro|commodities|market',
                        'finding': str,
                        'materiality': 'high|medium|low',
                        'affected_drivers': [driver names],
                        'direction': 'positive|negative',
                    },
                ],
                'driver_recommendations': {
                    'datacenter_growth': {'FY2028': 0.25, 'FY2029': 0.20},
                    'gm_improvement_bps': {'FY2028': 100},
                    ...
                },
                'narrative': str,
                'confidence': float (0.0-1.0),
            }
        """
        print(f"\n  [{self.name}] Seeking specialist input for {self.ticker}...")

        specialist_views = {}
        key_findings = []

        # 1. Query Macro Analyst view
        try:
            from agents.macro_analyst_agent import MacroAnalystAgent
            macro = MacroAnalystAgent()
            macro_view = macro._load_view()
            if macro_view:
                specialist_views['macro'] = {
                    'confidence': macro_view.confidence,
                    'summary': macro_view.summary,
                    'alerts': macro_view.alerts if hasattr(macro_view, 'alerts') else [],
                }
                # Extract high-confidence macro findings
                if macro_view.confidence > 0.6:
                    key_findings.append({
                        'source': 'macro_analyst',
                        'finding': macro_view.summary[:200] if macro_view.summary else 'Macro monitoring active',
                        'materiality': 'high' if macro_view.confidence > 0.8 else 'medium',
                        'affected_drivers': ['datacenter_growth', 'gaming_growth'],  # Macro affects growth
                        'direction': 'positive' if 'supportive' in (macro_view.summary or '').lower() else 'mixed',
                    })
        except Exception as e:
            print(f"    ⚠️  Could not load macro view: {e}")

        # 2. Query Commodities Agent view
        try:
            from agents.commodities_agent import CommoditiesAgent
            commodities = CommoditiesAgent()
            # Call commodities agent to get latest commodity view
            commodity_prompt = f"""
            Provide a brief update on key commodity impacts for {self.ticker}:
            1. HBM memory pricing (impact on gross margin)
            2. CoWoS/Advanced packaging capacity (impact on production volume)
            3. Any supply chain bottlenecks

            Focus on what has CHANGED since last update. Be specific with basis point estimates.
            Return JSON with: {{
                'hbm_impact_bps': float,
                'packaging_impact_bps': float,
                'volume_constraint_pct': float,
                'key_findings': [str],
                'materiality': 'high|medium|low',
            }}"""

            commodity_view = commodities.call_llm_json(commodity_prompt)
            specialist_views['commodities'] = commodity_view

            if commodity_view.get('materiality') in ['high', 'medium']:
                key_findings.append({
                    'source': 'commodities_agent',
                    'finding': f"HBM: {commodity_view.get('hbm_impact_bps', 0):+.0f}bps margin impact | "
                              f"Packaging: {commodity_view.get('packaging_impact_bps', 0):+.0f}bps",
                    'materiality': commodity_view.get('materiality', 'low'),
                    'affected_drivers': ['gm_improvement_bps'],
                    'direction': 'negative' if commodity_view.get('hbm_impact_bps', 0) < 0 else 'positive',
                })
        except Exception as e:
            print(f"    ⚠️  Could not query commodities: {e}")

        # 3. Query Market Analyst view (if it exists)
        try:
            market_view_path = Path('data/valuations/market_view_latest.json')
            if market_view_path.exists():
                with open(market_view_path) as f:
                    market_data = json.load(f)
                nvda_data = market_data.get('market_snapshot', {}).get('stocks', {}).get('NVDA', {})
                specialist_views['market'] = {
                    'price': nvda_data.get('price'),
                    'pe_forward_ntm': nvda_data.get('pe_forward_ntm'),
                    'pe_trailing_ttm': nvda_data.get('pe_trailing_ttm'),
                    'sector_3m_return': market_data.get('market_snapshot', {}).get('sector_rotation', {}).get('Semiconductors', {}).get('avg_3m_return'),
                    'technical_trend': market_data.get('market_snapshot', {}).get('technical_signals', {}).get('NVDA', {}).get('trend'),
                }

                # Extract market findings
                sector_perf = specialist_views['market'].get('sector_3m_return', 0)
                if abs(sector_perf) > 15:  # Material sector move
                    key_findings.append({
                        'source': 'market_analyst',
                        'finding': f"Semiconductor sector {'+' if sector_perf > 0 else ''}{sector_perf:.1f}% in 3 months ({specialist_views['market'].get('technical_trend')})",
                        'materiality': 'medium',
                        'affected_drivers': ['datacenter_growth', 'gaming_growth'],
                        'direction': 'positive' if sector_perf > 0 else 'negative',
                    })
        except Exception as e:
            print(f"    ⚠️  Could not load market view: {e}")

        # 4. Synthesize into driver recommendations
        driver_recommendations = {}

        # Start with current view baseline
        view = self._load_view()
        if view:
            for driver, periods in view.baseline_drivers.items():
                driver_recommendations[driver] = periods.copy()

        # Apply specialist recommendations
        if 'commodities' in specialist_views:
            comm_view = specialist_views['commodities']
            hbm_bps = comm_view.get('hbm_impact_bps', 0)
            pkg_bps = comm_view.get('packaging_impact_bps', 0)

            if hbm_bps != 0 or pkg_bps != 0:
                total_margin_bps = hbm_bps + pkg_bps
                if 'gm_improvement_bps' not in driver_recommendations:
                    driver_recommendations['gm_improvement_bps'] = {}
                # Apply to near-term periods
                for period in ['Q4-26', 'Q1-27', 'FY2028']:
                    if period in VALID_PERIODS_BY_TICKER.get(self.ticker, set()):
                        driver_recommendations['gm_improvement_bps'][period] = total_margin_bps

        # Build narrative
        narrative = f"Specialist input synthesis for {self.ticker}:\n"
        avg_confidence = 0.5
        if key_findings:
            avg_confidence = sum(0.8 if f['materiality'] == 'high' else 0.5 if f['materiality'] == 'medium' else 0.3
                                for f in key_findings) / len(key_findings)
            for finding in key_findings:
                narrative += f"\n  [{finding['source']}] {finding['finding']} (materiality: {finding['materiality']})"

        return {
            'timestamp': datetime.now().isoformat(),
            'specialist_views': specialist_views,
            'key_findings': key_findings,
            'driver_recommendations': driver_recommendations,
            'narrative': narrative,
            'confidence': avg_confidence,
            'action_items': f"Update {len([d for d in driver_recommendations if driver_recommendations[d]])} drivers"
                           if driver_recommendations else "No driver updates recommended",
        }

    def apply_specialist_recommendations(self, specialist_input: dict, threshold_confidence: float = 0.5) -> dict:
        """
        Apply specialist input recommendations to update the DCF driver view.

        Filters recommendations by:
        1. Overall confidence (threshold_confidence)
        2. Materiality of findings (high/medium > low)
        3. Identifies what is NEW vs already reflected in baseline

        Returns:
            {
                'applied_updates': {...},
                'skipped_updates': {...},
                'summary': str,
                'view_updated': bool,
            }
        """
        print(f"\n  [{self.name}] Applying specialist recommendations for {self.ticker}...")

        if specialist_input['confidence'] < threshold_confidence:
            print(f"    ⚠️  Confidence {specialist_input['confidence']:.0%} below threshold {threshold_confidence:.0%}, skipping")
            return {
                'applied_updates': {},
                'skipped_updates': specialist_input['driver_recommendations'],
                'summary': 'Recommendations below confidence threshold',
                'view_updated': False,
            }

        # Load current view
        view = self._load_view()
        if not view:
            print(f"    ⚠️  No existing view. Run ramp() first.")
            return {'applied_updates': {}, 'skipped_updates': {}, 'summary': 'No view to update', 'view_updated': False}

        # Identify what's NEW in the specialist recommendations
        applied = {}
        skipped = {}

        for driver, specialist_periods in specialist_input['driver_recommendations'].items():
            baseline_periods = view.baseline_drivers.get(driver, {})

            # Only update if values differ materially from baseline
            driver_applied = {}
            driver_skipped = {}

            for period, specialist_value in specialist_periods.items():
                baseline_value = baseline_periods.get(period, 0)

                # Check if this is NEW and MATERIAL (not just rounding)
                if isinstance(specialist_value, (int, float)) and isinstance(baseline_value, (int, float)):
                    delta = abs(specialist_value - baseline_value)
                    is_material = delta > (10 if driver.endswith('_bps') else 0.005)  # >10bps or >0.5pp

                    if is_material:
                        driver_applied[period] = specialist_value
                    else:
                        driver_skipped[period] = specialist_value

            if driver_applied:
                applied[driver] = driver_applied
            if driver_skipped:
                skipped[driver] = driver_skipped

        # Apply updates to view
        view_updated = False
        if applied:
            for driver, periods in applied.items():
                if driver not in view.baseline_drivers:
                    view.baseline_drivers[driver] = {}
                for period, value in periods.items():
                    old_val = view.baseline_drivers[driver].get(period)
                    view.baseline_drivers[driver][period] = value
                    print(f"    ✓ {driver}[{period}]: {old_val} → {value}")

            # Update metadata
            view.last_updated = datetime.now().isoformat()
            view.confidence = specialist_input['confidence']

            # Add to rationale
            specialist_sources = ', '.join(set(f['source'] for f in specialist_input['key_findings']))
            view.rationale = view.rationale or {}
            view.rationale['specialist_input'] = f"Updated based on {specialist_sources}"

            # Persist
            self._save_view(view)
            view_updated = True

        # Build summary
        summary_lines = []
        if applied:
            summary_lines.append(f"✓ Applied {len(applied)} drivers:")
            for driver in sorted(applied.keys()):
                summary_lines.append(f"    {driver} ({len(applied[driver])} periods)")

        if skipped:
            summary_lines.append(f"⊘ Skipped {len(skipped)} drivers (not material):")
            for driver in sorted(skipped.keys()):
                summary_lines.append(f"    {driver}")

        if not applied and not skipped:
            summary_lines.append("→ No changes (specialist input aligned with baseline)")

        return {
            'applied_updates': applied,
            'skipped_updates': skipped,
            'summary': '\n'.join(summary_lines),
            'view_updated': view_updated,
        }

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
