# Release Notes - Multi-Feature Update (Feb 14, 2026)

## Overview
This release adds 5 major features to the multi-agent portfolio management system:
1. **Cadence (CDNS) DCF Model** - Full DCF engine mirroring NVIDIA workflow
2. **Live Stock Price Integration** - Real-time market data via yfinance
3. **Portfolio Balancing** - Conviction-weighted allocation across SPY and individual stocks
4. **Expert Call Learning** - Analysts update views from expert transcripts (with appropriate skepticism)
5. **Enhanced PM-Analyst Dialogue** - Ticker-aware driver validation and improved request update workflow

---

## 1. Cadence (CDNS) DCF Model

### What's New
Complete DCF valuation infrastructure for Cadence Design Systems, mirroring the NVIDIA workflow:
- **DCF Tab Builder**: `build_cdns_dcf_tab.py` creates DCF tab in Canalyst Excel file
- **Python Engine**: `cdns_engine.py` with `CDNSDCFEngine` class (same interface as `NVDADCFEngine`)
- **7 Key Drivers**: 3 revenue segments + 4 margin drivers (vs NVDA's 8 drivers)

### Key Drivers
**Revenue Growth (3 segments):**
- `core_eda_growth` - Core EDA tools (row 13-14)
- `system_interconnect_growth` - System & interconnect analysis (row 16-17)
- `ip_growth` - IP licensing (row 18-19)

**Margin Improvements (4 drivers):**
- `gm_improvement_bps` - Gross margin (row 47/49, +1 sign)
- `rd_improvement_bps` - R&D expense (row 61/62, -1 sign)
- `ga_improvement_bps` - G&A expense (row 74/75, -1 sign)
- `sm_improvement_bps` - Sales & Marketing expense (row 87/88, -1 sign)

### Usage
```bash
# Build DCF tab in Excel
python3 build_cdns_dcf_tab.py

# Run engine standalone (baseline + example scenario)
python3 cdns_engine.py

# Verify PM has both engines loaded
python3 -c "from agents.pm_agent import PMAgent; pm = PMAgent(); print(list(pm.engines.keys()))"
# Output: ['NVDA', 'CDNS']

# Initialize CDNS analyst and ramp
python3 test_cdns_analyst.py --ramp
```

### Technical Notes
**Critical Fix**: Canalyst Excel model has NO cached formula values. The engine computes baselines from cached GAAP data:
- GAAP revenue from rows 339 (Product) + 340 (Services)
- Segment shares from rows 27, 29, 30
- Balance sheet from rows 1205 (Cash), 1236 (Debt), 521 (Shares)

**Result**: FY2026 baseline revenue $5,662M, implied price $134.59 (vs market $338.69, -60% upside)

### Files Added/Modified
- **New**: `cdns_engine.py` (780 lines), `build_cdns_dcf_tab.py` (370 lines), `test_cdns_analyst.py`
- **Modified**: `config.py` (updated CDNS entry with `has_full_model: True`, `engine_class: 'CDNSDCFEngine'`)
- **Modified**: `agents/pm_agent.py` (engine initialization for all companies with `has_full_model`)

---

## 2. Live Stock Price Integration

### What's New
Real-time market data integration via yfinance API. PM and analysts now fetch live prices instead of using stale Excel file data.

### Architecture
**Stock Market Agent** (`agents/stock_market_agent.py`):
- Monitors 5 semiconductor tickers + SPY
- Fetches live prices via yfinance with 5-minute cache TTL
- Provides market snapshot with price changes

### API Methods
```python
from agents.stock_market_agent import StockMarketAgent

agent = StockMarketAgent()

# Get live prices for multiple tickers
prices = agent.get_current_prices(['NVDA', 'CDNS'])
# Returns: {'NVDA': {'price': 182.81, 'prev_close': 180.50, 'change_pct': 0.0128, ...}, ...}

# Get single ticker price (with caching)
price = agent.get_price('NVDA', use_cache=True)
# Returns: 182.81

# Get full market snapshot
snapshot = agent.get_market_snapshot()
# Returns: {'timestamp': '...', 'summary': '...', 'tickers': [...], 'prices': {...}}
```

### PM Integration
PM agent now fetches live prices before DCF computation:
```python
# In balance_portfolio() and request_analyst_update()
live_prices = self.stock_market_agent.get_current_prices(['NVDA', 'CDNS'])
for ticker, engine in self.engines.items():
    result = engine.compute_dcf()  # Uses file price
    live_price_data = live_prices.get(ticker, {})
    current_price = live_price_data.get('price', result['current_price'])  # Override with live
    upside = (implied_price / current_price - 1)  # Recalculate with live price
```

### Usage
```bash
# Test live price fetching
python3 test_stock_prices.py                      # Market snapshot
python3 test_stock_prices.py --ticker NVDA        # Single ticker
python3 test_stock_prices.py --tickers NVDA CDNS  # Multiple tickers
```

### Files Added/Modified
- **Modified**: `agents/stock_market_agent.py` (added `get_current_prices()`, `get_price()`, `get_market_snapshot()`)
- **Modified**: `agents/pm_agent.py` (integrated live price fetching in `balance_portfolio()` and `request_analyst_update()`)
- **New**: `test_stock_prices.py`

---

## 3. Portfolio Balancing

### What's New
PM agent can now allocate portfolio across S&P 500 (SPY) and individual stocks based on DCF valuations, analyst confidence, and macro context.

### Allocation Logic
1. **Fetch live prices** for all tickers
2. **Compute DCF valuations** with live prices (overrides file prices)
3. **LLM allocation decision** considering:
   - Upside/downside vs implied price
   - Analyst confidence levels (higher confidence → stronger conviction)
   - Macro environment (growth outlook, risk factors)
   - Diversification constraints (max 30% per stock)

### Usage
```python
from agents.pm_agent import PMAgent

pm = PMAgent()
allocation = pm.balance_portfolio()

# Output:
# {
#   'timestamp': '20260214_212143',
#   'allocations': {'SPY': 0.7, 'NVDA': 0.15, 'CDNS': 0.15},
#   'rationale': '...',
#   'confidence': 0.85,
#   'risk_level': 'moderate',
#   'valuations': {...},
#   'macro_context': {...}
# }
```

### Example Output
```bash
python3 test_balance_portfolio.py
```
**Result** (as of Feb 14, 2026):
- **70% SPY** - Defensive positioning given both stocks overvalued
- **15% NVDA** - Modest allocation (-38% upside, 80% confidence)
- **15% CDNS** - Modest allocation (-63% upside, 80% confidence)

**Rationale**: "Given the current macroeconomic environment characterized by moderate growth and easing inflation, alongside an inverted yield curve signaling potential recessionary concerns, a cautious approach is warranted. Both NVDA and CDNS are significantly overvalued based on implied valuations with high analyst confidence, suggesting limited upside potential."

### Files Added/Modified
- **Modified**: `agents/pm_agent.py` (added `balance_portfolio()` method)
- **New**: `test_balance_portfolio.py`

---

## 4. Expert Call Learning

### What's New
Company analysts can now update their views based on expert call transcripts. The system processes transcripts with appropriate skepticism ("grain of salt").

### Features
- **Credibility Assessment**: Evaluates expert background, recency, specificity (0-100%)
- **Selective Updates**: Only updates view if expert provides concrete, credible insights that corroborate existing trends
- **Validation**: Applies same driver validation as news-based updates
- **Format Support**: .docx and .txt files via python-docx

### Processing Logic
```python
def learn_from_expert_call(self, expert_call_text: str) -> AnalystView:
    # LLM prompt includes:
    # - "Expert calls should be taken with a GRAIN OF SALT"
    # - "Experts may have outdated information (former employees)"
    # - "Use as ONE data point, not primary source of truth"
    # - "Only update if CONCRETE, CREDIBLE insights provided"

    result = self.call_llm_json(prompt)
    expert_cred = result.get('expert_credibility', 0.5)  # 0-100%

    if not result.get('warrants_change', False):
        return view  # No update

    # Validate and update drivers conservatively
```

### Real-World Test Results

**Test 1: Neutral Expert Call** (38K chars, Former VP Product)
- **Credibility**: 70% (credible role but left 1yr ago, some specifics but anecdotal)
- **Decision**: NO UPDATE
- **Reason**: "Expert insights largely corroborate existing view. No concrete new data points that warrant changing baseline drivers."

**Test 2: Bullish Expert Call** (5.8K chars, Former VP Product)
- **Credibility**: 75% (recent insider, specific customer metrics, but some claims unverifiable)
- **Decision**: UPDATE
- **Changes**:
  - Core EDA growth: +2% → +3% (stronger ChipStack adoption)
  - Gross margin: +20bps → +40bps (premium pricing model)
  - Confidence: 80% → 85%

### Usage
```bash
# Process expert call transcript
python3 test_expert_call.py --ticker CDNS --file "Expert calls/test_cdns_bullish_call.txt"

# Output shows:
# - Current view before expert call
# - Expert credibility assessment
# - Updated view after expert call
# - Driver changes (if any)
```

### Files Added/Modified
- **Modified**: `agents/company_analyst_agent.py` (added `learn_from_expert_call()` method)
- **New**: `test_expert_call.py`
- **New**: `Expert calls/` directory with sample transcripts

---

## 5. Enhanced PM-Analyst Dialogue

### What's New
**Ticker-Aware Driver Validation**: System now validates drivers based on ticker-specific schemas (NVDA has 8 drivers, CDNS has 7).

**Improved Request Update Workflow**: PM challenges analyst recommendations through multi-turn dialogue with concessions and defenses.

### Ticker-Specific Driver Schemas
```python
# In agents/company_analyst_agent.py
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
```

### PM Challenge/Response Dialogue
Example from CDNS analyst update session:

**PM Challenge 1**: "Your gross margin expansion assumes 160bps improvement by FY2028. What gives you confidence that Cadence can sustain premium pricing as AI-driven EDA tools mature?"

**Analyst Response**: "I concede this is aggressive..." → **CONCEDE** (revised from +160bps to +120bps)

**PM Challenge 4**: "You project 25% IP growth through FY2028... How sustainable is this given potential market saturation?"

**Analyst Response**: "I stand by the 25% growth projection..." → **DEFEND** (maintained +25%)

**PM Final Decision**: MODIFY with 70% confidence (more conservative than analyst's 80%)

### Files Modified
- **Modified**: `agents/company_analyst_agent.py` (added `VALID_DRIVERS_BY_TICKER`, ticker-aware validation)
- **Modified**: `agents/pm_agent.py` (added ticker parameter to `_validate_drivers()`, dynamic driver lists in prompts)

---

## Installation & Dependencies

### New Dependencies
```bash
pip3 install yfinance python-docx
```

### Verify Installation
```bash
# Check all engines loaded
python3 -c "from agents.pm_agent import PMAgent; pm = PMAgent(); print(pm.engines.keys())"
# Expected: dict_keys(['NVDA', 'CDNS'])

# Check live price fetching
python3 test_stock_prices.py --ticker NVDA
# Expected: Live price from yfinance

# Check portfolio balancing
python3 test_balance_portfolio.py
# Expected: Allocation across SPY, NVDA, CDNS
```

---

## Known Issues & Limitations

1. **CDNS Baseline Data**: Canalyst Excel model lacks cached formula values. Engine computes baselines from GAAP data, which may not perfectly match analyst model's Non-GAAP adjustments.

2. **Expert Call Credibility**: Credibility assessment is LLM-based and subjective. System errs on conservative side (requires 70%+ credibility and concrete data points to update).

3. **Live Price Caching**: 5-minute cache TTL may be too long for volatile trading. Consider reducing for production.

4. **Portfolio Allocation**: Current logic is qualitative (LLM-based). Future versions could add quantitative optimization (e.g., mean-variance optimization with conviction weightings).

---

## Testing

All test scripts assume CWD is `agent-alpha/`:

```bash
# CDNS DCF
python3 build_cdns_dcf_tab.py           # Build DCF tab in Excel
python3 cdns_engine.py                   # Run engine (baseline + scenario)

# CDNS Analyst
python3 test_cdns_analyst.py --ramp      # Initialize and ramp analyst
python3 test_cdns_analyst.py --monitor   # Monitor mode (check for updates)

# PM Request Update (multi-turn dialogue)
python3 pm_agent_interface.py            # Interactive PM interface
# Then: pm.request_analyst_update('CDNS')

# Portfolio Balancing
python3 test_balance_portfolio.py        # Get current allocation

# Live Prices
python3 test_stock_prices.py             # Market snapshot
python3 test_stock_prices.py --ticker NVDA

# Expert Calls
python3 test_expert_call.py --ticker CDNS --file "Expert calls/test_cdns_bullish_call.txt"
```

---

## Architecture Summary

```
PMAgent
├── engines: {NVDA: NVDADCFEngine, CDNS: CDNSDCFEngine}
├── macro_analyst: MacroAnalystAgent
├── stock_market_agent: StockMarketAgent (NEW)
├── balance_portfolio() → allocation dict (NEW)
└── request_analyst_update(ticker)
    ├── CompanyAnalystAgent.propose_update()
    │   ├── Fetch latest news (20 articles)
    │   ├── Analyze macro context
    │   ├── Generate driver recommendations
    │   └── learn_from_expert_call(transcript) (NEW)
    ├── PM challenges recommendations (4 rounds)
    ├── Analyst concedes or defends
    └── PM makes final decision (ACCEPT/MODIFY/REJECT)
```

---

## Contributors
- Matthew Wolfman (@matthewwolfman)

## Date
February 14, 2026
