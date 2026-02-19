# Council of Agents for Semiconductor Portfolio Construction — Project Summary

**Status**: Phase 4 (DCF Valuation) fully operational across 5 semiconductor companies
**Last Updated**: February 17, 2026
**Companies Covered**: NVIDIA (NVDA), Cadence (CDNS), TSMC (TSM), CoreWeave (CRWV), ASML

---

## Executive Overview

This project implements a **multi-agent system** that analyzes events in the semiconductor industry and produces DCF-backed investment recommendations for a portfolio manager (PM). The system orchestrates 7 specialized agents to detect events, build causal graphs, debate implications, and ultimately adjust DCF valuations.

**Key Achievement**: Complete end-to-end pipeline for 5 major semiconductor stocks, including Excel-based DCF models with adjustable drivers and Python computational engines.

---

## Architecture

### Agent Hierarchy
```
Portfolio Manager (PM) — Orchestrator
├── 5 Domain Experts
│   ├── Politics Agent — Geopolitics, trade policy, sanctions
│   ├── Stock Market Agent — Technicals, liquidity, crowding
│   ├── Commodities Agent — Memory pricing, packaging capacity
│   ├── Tech Publications Agent — Industry trends, product launches
│   └── Macro Agent — Interest rates, GDP, inflation, FX
├── 5 Company Analysts (1 per stock)
│   ├── NVDA Analyst
│   ├── CDNS Analyst
│   ├── TSM Analyst
│   ├── CRWV Analyst
│   └── ASML Analyst
└── Independent Macro Analyst — Broader macro outlook
```

### 4-Phase Pipeline

**Phase 1: Event Detection**
- All domain agents scan news input for events
- Events classified by severity (critical → low)
- Deduplication and ranking by impact

**Phase 2: Causal Graph Construction**
- For each event, domain agents propose causal links
- Links capture metric, company, direction, confidence
- Conflict detection when agents disagree on direction

**Phase 3: Multi-Agent Debate**
- For each debatable metric, agents defend positions
- PM asks probing questions to distinguish leading vs lagging indicators
- Devil's Advocate challenges emerging consensus
- PM resolves debate → single agreed driver adjustment per metric

**Phase 4: DCF Valuation**
- Driver adjustments applied to Python DCF engine
- New implied price computed
- Valuation saved with full audit trail

---

## Five DCF Engines

All engines follow the same pattern:
1. **Read baseline** from Excel Model tab
2. **Define drivers** (segment growth, margin improvements)
3. **Compute DCF** in 7 steps: revenue → margins → UFCF → WACC discount → terminal value → equity bridge
4. **Support adjustments** via `update_drivers()` and `compute_dcf()`

### 1. NVIDIA (NVDA) — GPU Designer

**File**: `models/pm_agent_interface.py` → `NVDADCFEngine`

**Revenue Drivers** (5 segments):
- `datacenter_growth` (67% of revenue)
- `gaming_growth` (20%)
- `automotive_growth` (3%)
- `proviz_growth` (6%)
- `oem_growth` (4%)

**Margin Drivers** (3):
- `gm_improvement_bps` (baseline: +150 bps improvement)
- `rd_improvement_bps` (baseline: +60 bps)
- `sga_improvement_bps` (baseline: +30 bps)

**Periods**: Quarterly Q4-26 through Q4-27, Annual FY2028-FY2030

**WACC**: 13.3% (rf=4.25%, beta=1.65, risk premium=8%)

**Valuation Dynamics**:
- Margin expansion from AI/datacenter leverage
- R&D investments declining as % of revenue
- Heavy CapEx for manufacturing partnerships

---

### 2. Cadence (CDNS) — EDA Software

**File**: `models/cdns_engine.py` → `CDNSDCFEngine`

**Revenue Drivers** (3 segments):
- `core_eda_growth`
- `system_interconnect_growth`
- `ip_growth`

**Margin Drivers** (4 — more granular than NVDA):
- `gm_improvement_bps`
- `rd_improvement_bps` (separate)
- `ga_improvement_bps` (G&A, separate from R&D)
- `sm_improvement_bps` (S&M)

**Periods**: Quarterly Q3-26, Q4-26, Annual FY2027-FY2029

**WACC**: 10.4% (rf=4.25%, beta=1.15, risk premium=8%)

**Valuation Dynamics**:
- Software margin expansion (high gross margin, operating leverage)
- Dependent on semiconductor capex cycles (TSMC/ASML growth → higher EDA spending)
- Licensing model provides recurring revenue

---

### 3. TSMC (Taiwan Semiconductor) — Foundry

**File**: `models/tsmc_engine.py` → `TSMCDCFEngine`

**Revenue Drivers** (6 segments by end market):
- `smartphone_growth`
- `hpc_growth` (35% of revenue — AI accelerators)
- `iot_growth`
- `automotive_growth`
- `digital_consumer_growth`
- `other_growth` (residual)

**Margin Drivers** (3):
- `gm_improvement_bps`
- `opex_improvement_bps`
- `tax_rate_bps`

**Periods**: Annual FY2027-FY2029 only

**WACC**: 11.8% (rf=4.25%, beta=0.95, risk premium=8%)

**Valuation Dynamics**:
- Capital-intensive (28% capex as % of revenue)
- High fixed-cost manufacturing → operating leverage in upswings
- Exposed to smartphone/PC cycles (downside) and AI/HPC (upside)
- Geopolitical risk (Taiwan location)

---

### 4. CoreWeave (CRWV) — GPU Cloud Rental

**File**: `models/crwv_engine.py` → `CoreWeaveDCFEngine`

**Revenue Drivers** (1 — single business line):
- `revenue_growth` (40% baseline)

**Margin Drivers** (3):
- `ebitda_margin_improvement_bps`
- `opex_improvement_bps`
- `tax_rate_bps`

**Periods**: Annual FY2027-FY2029 only

**WACC**: 16.2% (rf=4.25%, beta=1.50, risk premium=8%) — Highest risk

**Valuation Dynamics**:
- Neocloud/GPU-as-a-Service business model
- Extreme capex intensity (35% of revenue for GPU purchases)
- Pre-profitability in baseline (negative FCF in early years)
- High growth but high risk (direct exposure to GPU cycles)

---

### 5. ASML — Semiconductor Equipment

**File**: `models/asml_engine.py` → `ASMLDCFEngine`

**Revenue Drivers** (6 equipment types):
- `euv_growth` (40% of revenue — most valuable)
- `arfi_growth` (20%)
- `arf_growth` (15%)
- `krf_growth` (10%)
- `iline_growth` (10%)
- `metrology_growth` (5%)

**Margin Drivers** (1):
- `gm_improvement_bps`

**Periods**: Annual FY2027-FY2029 only

**WACC**: 10.7% (rf=4.25%, beta=0.80, risk premium=8%) — Lower risk

**Valuation Dynamics**:
- Asset-light equipment manufacturing (3% capex as % of revenue)
- High gross margins (52% baseline) and pricing power from EUV dominance
- Exposed to semiconductor capex cycles with 1-2 year lag
- EUV = strategic constraint for leading-edge chipmakers

---

## Commodity Monitoring System (Phase 1)

### Memory Pricing Monitor

**File**: `tools/memory_pricing_monitor.py`

Tracks DRAM/HBM pricing from **free public sources**:
- TrendForce market reports
- Semiconductor supply chain blogs
- Earnings call transcripts
- SEMI industry reports

**Key Metrics**:
- HBM spot prices (weekly updates)
- DRAM ASP trends
- Lead time indicators
- Inventory weeks at component brokers

**DCF Impact Modeling**:
- HBM +20% → NVDA gross margin -70 bps, TSMC +240 bps, CRWV -180 bps
- DRAM +10% → milder impact on all stocks

**Cadence**: Weekly monitoring, integrated into commodities agent

---

### Advanced Packaging Monitor

**File**: `tools/advanced_packaging_monitor.py`

Tracks **CoWoS, substrates, HBM stacking, chiplets**:
- CoWoS capacity (bottleneck: 75K → 120K wafers/month)
- ASE/Unimicron substrate utilization (92% — tightest supplier)
- HBM stacking constraints
- Advanced packaging cost trends

**Production Constraints**:
- NVIDIA GPU production limited to ~63% of demand due to CoWoS
- Pricing power from scarcity vs cost pressure from high capex
- Lead time to expand capacity: 18-24 months

**DCF Impact Modeling**:
- CoWoS constrained → NVIDIA pricing power but production limit
- ASML benefits from substrate/packaging equipment demand
- TSMadvantages from foundry service scarcity

**Cadence**: Bi-weekly updates, integrated into commodities agent

---

## PM Agent Workflows

### 1. Full Pipeline (News-Driven)

```python
pm = PMAgent()
result = pm.run_full_pipeline(
    news_input="NVIDIA announces new H100 specs...",
    target_company='NVDA'
)
```

**Output**:
- Detected events and severity
- Causal graph with 10+ links
- Debate rounds with multi-agent positions
- Resolved driver adjustments
- Implied price delta vs baseline
- Valuation JSON saved to `data/valuations/`

**Execution Time**: 60-120 seconds, 10K-15K tokens

---

### 2. Update Request (Analyst-Driven)

```python
session = pm.request_update('NVDA')
```

**Flow**:
1. Analyst brief (current view + recommended changes)
2. PM challenges (2-4 pointed questions)
3. Analyst responses (defend or concede)
4. PM decision (accept/modify/reject)
5. DCF revaluation (if accepted/modified)

**Output**: `UpdateSession` JSON with full dialogue, rationale, confidence

**Execution Time**: 30-60 seconds

---

### 3. Portfolio Balancing

```python
allocation = pm.balance_portfolio()
```

**Input**: Live stock prices + baseline DCF valuations for all 5 stocks + macro outlook

**Output**:
- Portfolio weights for SPY + all 5 stocks
- Allocation rationale
- Risk level (conservative/moderate/aggressive)
- Max 30% per stock constraint enforced

**Example**:
```
SPY:  60%  ($600K)
NVDA: 20%  ($200K)
TSMC: 10%  ($100K)
CDNS: 5%   ($50K)
CRWV: 3%   ($30K)
ASML: 2%   ($20K)
```

---

## File Structure

```
agent-alpha/
├── models/
│   ├── __init__.py
│   ├── pm_agent_interface.py        # NVDADCFEngine (8 drivers)
│   ├── cdns_engine.py                # CDNSDCFEngine (7 drivers)
│   ├── tsmc_engine.py                # TSMCDCFEngine (8 drivers)
│   ├── crwv_engine.py                # CoreWeaveDCFEngine (4 drivers)
│   ├── asml_engine.py                # ASMLDCFEngine (6 drivers)
│   ├── event.py                      # Event model
│   ├── causal_graph.py               # CausalGraph, CausalLink
│   ├── debate.py                     # DebatePosition, DebateRound, etc
│   ├── update_session.py             # AnalystUpdateBrief, PMChallenge, etc
│   └── base_model.py                 # Base JSON serialization
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py                 # BaseAgent (LLM wrapper, call_log)
│   ├── pm_agent.py                   # PMAgent — orchestrator
│   ├── politics_agent.py             # Politics & geopolitics events
│   ├── stock_market_agent.py         # Technical analysis, price data
│   ├── commodities_agent.py          # Memory + packaging monitoring
│   ├── tech_publications_agent.py    # Product launches, benchmarks
│   ├── macro_agent.py                # Macro conditions
│   ├── company_analyst_agent.py      # Company-specific analyst (ramp/monitor)
│   └── macro_analyst_agent.py        # Independent macro analyst
│
├── tools/
│   ├── memory_pricing_monitor.py     # HBM/DRAM tracking (free sources)
│   ├── advanced_packaging_monitor.py # CoWoS, substrates, capacity
│   └── macro_news_fetcher.py         # Macro news aggregation
│
├── tests/
│   ├── test_all_dcf_engines.py       # Integration test for 5 engines
│   ├── test_analyst.py               # Company analyst tests
│   ├── test_macro_analyst.py         # Macro analyst tests
│   └── test_commodity_monitoring.py  # Memory + packaging monitoring
│
├── scripts/
│   ├── build_dcf_tab.py              # NVIDIA DCF tab builder
│   ├── build_cdns_dcf_tab.py         # Cadence DCF tab builder
│   ├── build_tsmc_dcf_tab.py         # TSMC DCF tab builder
│   ├── build_crwv_dcf_tab.py         # CoreWeave DCF tab builder
│   └── build_asml_dcf_tab.py         # ASML DCF tab builder
│
├── financial_models/
│   ├── NVIDIA NVDA US.xlsx           # NVDA analyst model + DCF tab
│   ├── Cadence Design CDNS US.xlsx   # CDNS analyst model + DCF tab
│   ├── Taiwan Semiconductor Manufacturing Company TSM US.xlsx
│   ├── CoreWeave CRWV US.xlsx
│   └── ASML Holding ASML NA.xlsx
│
├── data/
│   ├── events/                       # Event JSON by timestamp
│   ├── causal_graphs/                # Causal graph JSON
│   ├── debates/                      # Debate session JSON
│   ├── valuations/                   # DCF valuation results
│   ├── analyst_views/                # Company analyst current views
│   ├── update_sessions/              # Update request dialogue logs
│   ├── macro_analyst/                # Macro analyst current views
│   └── news_cache/                   # Cached news for commodities/macro
│
├── config.py                         # Central configuration (COMPANIES, SUPPLY_CHAIN, WACC)
├── main.py                           # Entry point (run_full_pipeline, request_update)
├── .env                              # OpenAI API key
├── .gitignore
└── docs/
    ├── PROJECT_SUMMARY.md            # This file
    ├── MEMORY_PRICING_MONITORING.md  # Commodity monitoring details
    └── CLAUDE.md                     # Instructions for Claude Code
```

---

## Key Implementation Details

### DCF Computation (7-Step Pattern)

All 5 engines follow the same computational flow:

```
Step 1: Build Revenues
  - Read base years from Excel
  - Apply segment/product-specific growth drivers
  - Project forward 3-4 years

Step 2: Compute Margins
  - Gross margin improvement from driver adjustments
  - Operating expense improvements (R&D, G&A, S&M where applicable)
  - Cascading baseline from historical periods
  - Caps to prevent unrealistic assumptions (e.g., max EBIT margin 35%)

Step 3: Compute EBIT
  - EBIT = Revenue × EBIT Margin %

Step 4: Compute UFCF (Unlevered Free Cash Flow)
  - NOPAT = EBIT × (1 - tax_rate)
  - Add back D&A (non-cash)
  - Subtract CapEx (cash outflow)
  - Subtract change in working capital
  - Result: UFCF = NOPAT + D&A - CapEx - ∆NWC

Step 5: Compute WACC
  - WACC = rf + beta × MRP
  - Fixed assumptions (not adjustable by PM)
  - rf=4.25%, MRP=8%
  - Beta varies by company: NVDA=1.65, CDNS=1.15, TSM=0.95, CRWV=1.50, ASML=0.80

Step 6: Discount Cash Flows
  - PV(UFCF) = Sum over projections: UFCF[t] / (1+WACC)^t
  - Terminal Value = UFCF[final] × (1 + g) / (WACC - g)
  - PV(TV) = TV / (1+WACC)^4
  - g = 2% (conservative perpetual growth)

Step 7: Equity Bridge
  - Enterprise Value = PV(UFCF) + PV(TV)
  - Less: Net Debt (cash - short/long-term debt)
  - Equity Value = EV - Net Debt
  - Shares Outstanding (millions)
  - Implied Price = Equity Value / Shares
  - Upside = (Implied - Current) / Current
```

---

## Integration Points

### Config Registry

`config.py` maintains the **COMPANIES** dict:

```python
COMPANIES = {
    'NVDA': {
        'name': 'NVIDIA',
        'ticker': 'NVDA',
        'segment': ['datacenter', 'gaming', 'automotive', 'proviz', 'oem'],
        'excel_path': 'financial_models/NVIDIA NVDA US.xlsx',
        'engine_class': 'NVDADCFEngine',
        'has_full_model': True,
    },
    # ... CDNS, TSM, CRWV, ASML
}
```

- **has_full_model=True** → DCF engine loaded at PM init
- **engine_class** → Class name from _ENGINE_MAP
- **excel_path** → Path to analyst model (relative to project root)
- **segments** → For analyst agent revenue detail

### Supply Chain Map

```python
VALUE_CHAIN = {
    'equipment': ['ASML'],
    'foundry': ['TSM'],
    'eda': ['CDNS'],
    'gpu_design': ['NVDA'],
    'neocloud': ['CRWV'],
}

SUPPLY_CHAIN = {
    'ASML': {'downstream': ['TSM']},
    'TSM': {'upstream': ['ASML', 'CDNS'], 'downstream': ['NVDA']},
    'CDNS': {'downstream': ['TSM', 'NVDA']},
    'NVDA': {'upstream': ['TSM'], 'downstream': ['CRWV']},
    'CRWV': {'upstream': ['NVDA']},
}
```

Used by domain agents to identify causal connections between companies.

---

## Test Coverage

### `test_all_dcf_engines.py`

Integration test verifying:
1. ✅ PM agent initializes all 5 DCF engines
2. ✅ All engines compute baseline valuations
3. ✅ All engines accept driver modifications
4. ✅ Baseline valuations are reproducible

**Run**:
```bash
python3 tests/test_all_dcf_engines.py
```

**Output**:
- Engine initialization log
- Driver inventory for each company
- Baseline valuations (implied price, upside %)
- Driver modification examples

---

## Known Limitations

1. **Implied Prices Are Theoretical**
   - Excel models contain analyst assumptions that may be dated
   - Real market prices (184.97 for NVDA, 120 for TSM, etc.) incorporate additional risk factors
   - DCF valuations here are **starting points for scenario analysis**, not absolute fair values

2. **No Real-Time Excel Updates**
   - `engine.save()` method is stubbed (doesn't actually write back to Excel)
   - Could be enabled for true Excel/Python integration

3. **Limited Commodity Data**
   - Phase 1 uses free sources only (TrendForce, earnings calls, blogs)
   - Would benefit from paid data (DRAMeXchange, Gartner, IDC) for higher confidence
   - $4K+/year cost has been deferred

4. **Macro Analyst Is Independent**
   - Provides broader context (rates, inflation, supply chain) but not automated triggers
   - Could be enhanced with macro scenario testing (recession, inflation shock, etc.)

---

## Future Enhancements

### Phase 2: Automated Macro Scenarios
- Recession scenario: demand ↓10%, margins ↓200 bps
- Inflation scenario: capex ↑15%, gross margin under pressure
- Supply shock scenario: capex ↑30%, pricing power for foundry/equipment

### Phase 3: Sector Rotation
- Identify when value chain shifts (e.g., foundry capex boom → equipment lead time)
- Anticipate second-order effects (ASML → TSMC → NVDA leads by 6 months)

### Phase 4: Real-Time Integration
- Connect to earnings call APIs (Seeking Alpha, Yahoo Finance transcripts)
- Auto-trigger analyst updates when key metrics reported
- Save revised drivers back to Excel for permanent tracking

### Phase 5: Portfolio Hedging
- Identify uncorrelated bets (e.g., long NVDA, short CRWV when memory tight)
- Correlation matrix of stocks + macro factors
- Hedge recommendations (VIX, oil, currency pairs)

---

## Running the System

### Quick Start
```bash
cd agent-alpha

# Initialize PM with all 5 DCF engines
python3 main.py

# Run news-driven analysis on NVIDIA
pm = PMAgent()
result = pm.run_full_pipeline(
    "NVIDIA releases new H100, demand surge expected",
    target_company='NVDA'
)

# Or request analyst update
session = pm.request_update('TSM')

# Or balance entire portfolio
allocation = pm.balance_portfolio()
```

### Entry Points

1. **Full Pipeline** (Phase 1-4): `pm_agent.run_full_pipeline(news_input, target_company)`
2. **Analyst Update** (Phase 4 only): `pm_agent.request_update(ticker)`
3. **Portfolio Balancing**: `pm_agent.balance_portfolio()`

---

## Authors & Attribution

**Project**: Stanford CS372 Final Project
**Course**: Causal Reasoning in Semiconductor Value Chain
**Instructor**: [Course staff]
**Student**: [Your name]
**Implementation**: Claude Code (claude.ai/code)

---

## Appendix: Quick Reference

### Driver Ranges by Company

| Company | Driver | Baseline | Range | Impact |
|---------|--------|----------|-------|--------|
| NVDA | datacenter_growth | 67% | -50% to +150% | ±$50-80 per share |
| NVDA | gm_improvement_bps | +150 | -100 to +300 | ±$20-40 per share |
| CDNS | core_eda_growth | 1% | -50% to +100% | ±$10-20 per share |
| CDNS | gm_improvement_bps | +10 | -50 to +100 | ±$5-10 per share |
| TSM | hpc_growth | 25% | 0% to +100% | ±$10-30 per share |
| TSM | gm_improvement_bps | 0 | -100 to +200 | ±$15-30 per share |
| CRWV | revenue_growth | 40% | -50% to +150% | ±$3-8 per share |
| ASML | euv_growth | 15% | -30% to +80% | ±$15-40 per share |
| ASML | gm_improvement_bps | 0 | -200 to +300 | ±$20-50 per share |

---

**End of Project Summary**
