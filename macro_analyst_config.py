"""
Independent Macro Analyst Configuration — Sameer's file.
No imports from the project. Standalone config for the macro analyst agent.
"""

# ── Tracked FRED Indicators & Change Thresholds ──────────────
# Keys match fred_data.SERIES; thresholds are absolute changes that trigger reassessment.
TRACKED_INDICATORS = {
    'fed_funds':    {'fred_key': 'fed_funds',    'threshold': 0.25, 'unit': '%',  'label': 'Fed Funds Rate'},
    '10yr_yield':   {'fred_key': '10yr_yield',   'threshold': 0.20, 'unit': '%',  'label': '10Y Treasury Yield'},
    '2yr_yield':    {'fred_key': '2yr_yield',    'threshold': 0.20, 'unit': '%',  'label': '2Y Treasury Yield'},
    'cpi':          {'fred_key': 'cpi',          'threshold': 1.0,  'unit': 'idx', 'label': 'CPI Index'},
    'gdp':          {'fred_key': 'gdp',          'threshold': 200,  'unit': '$B',  'label': 'GDP'},
    'unemployment': {'fred_key': 'unemployment', 'threshold': 0.3,  'unit': '%',  'label': 'Unemployment Rate'},
    'pce':          {'fred_key': 'pce',          'threshold': 0.5,  'unit': 'idx', 'label': 'PCE Price Index'},
}

# ── Alert Settings ────────────────────────────────────────────
ALERT_CONFIDENCE_THRESHOLD = 0.5    # Don't generate alerts below this confidence
ALERT_MATERIALITY_THRESHOLD = 0.3   # Minimum indicator change (as fraction of threshold) to alert
ALERT_RECIPIENT_TICKERS = ['NVDA', 'TSM', 'ASML', 'CDNS', 'CRWV']

# ── Briefing Settings ────────────────────────────────────────
BRIEFING_RECIPIENT_TICKERS = ['NVDA', 'TSM', 'ASML', 'CDNS', 'CRWV']
BRIEFING_MAX_INDICATORS = 10

# ── News Sources (macro-focused RSS feeds) ────────────────────
MACRO_NEWS_SOURCES = [
    'https://www.federalreserve.gov/feeds/press_all.xml',
    'https://www.bls.gov/feed/cpi_latest.rss',
    'https://www.bea.gov/rss.xml',
]
CNBC_ECONOMY_RSS_URL = 'https://www.cnbc.com/id/20910258/device/rss/rss.html'
ALPHA_VANTAGE_TOPICS = 'economy_monetary,economy_fiscal,economy_macro'
FINNHUB_NEWS_CATEGORY = 'general'
MACRO_NEWS_MAX_ITEMS = 30

# ── Schedule Guidance ─────────────────────────────────────────
MONITOR_INTERVAL_HOURS = 12
NIGHTLY_BRIEFING_HOUR = 21  # 9 PM local time

# ── LLM Tuning ───────────────────────────────────────────────
TEMPERATURE_OVERRIDE = 0.15  # Slightly lower than default for macro analysis
SYSTEM_PROMPT_ADDENDUM = """
When assessing macro conditions, prioritize:
1. Direction and velocity of rate changes over absolute levels
2. Yield curve shape (2Y-10Y spread) as a recession signal
3. Real interest rates (nominal minus CPI/PCE) for tech valuations
4. Capex cycle implications — rates affect corporate borrowing costs
5. Currency effects on multinational semiconductor companies
"""
