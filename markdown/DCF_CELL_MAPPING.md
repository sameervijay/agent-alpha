# DCF Cell Mapping Analysis
## TSMC, CoreWeave, ASML Financial Models

**Analysis Date:** February 17, 2026
**Purpose:** Identify all key cells for DCF analysis and Python engine mapping

---

## EXECUTIVE SUMMARY

All three companies use standardized Canalyst/AlphaSense analyst models with:
- **Model Sheet**: Contains historical data, forecasts, and key metrics
- **Column Structure**: Mix of annual (FY) and quarterly (Q1-Q4) data
- **Time Period**: Typically 4-6 historical years + 6-10 forecast years
- **Row Labels**: Column A contains metric descriptions
- **Data**: Columns B onwards contain numerical values

### Key Metadata
- Row 4: Date/Period headers
- Row 5: Period labels (FY2025, Q1-25, etc.)
- Row 1: Company name
- Row 6: Section headers (e.g., "Revenue Build", "Operating Expense Forecasting")

---

## 1. TSMC (Taiwan Semiconductor Manufacturing Company TSM US.xlsx)

### Model Dimensions
- **Dimensions**: A1:CC1106 (1,106 rows × 81 columns)
- **Historical Data**: From FY2009 to present
- **Forecast Horizon**: Extends to FY2030+

### Column Structure

| Metric | Columns | Description |
|--------|---------|-------------|
| **Historical Years** | C-G | FY2009 through FY2013 (example) |
| **Quarters** | H-K | Q1-Q4 of next fiscal year |
| **Annual FY** | L | Full year |
| **Future Quarters** | M-U | Quarterly forecasts |
| **Forecast Years** | AA-AF+ | FY2025, FY2026, FY2027, etc. |

### Key Revenue Metrics

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Revenue Build Section** | 6 | A | Header | Section divider |
| **Smartphone Revenue** | 7 | A + data cols | mm | Segment revenue |
| **Q/Q Smartphone Growth** | 8 | Data cols | % | Sequential quarter |
| **Y/Y Smartphone Growth** | 9 | Data cols | % | Year-over-year |
| **High Performance Computing Revenue** | 10 | A + data cols | mm | Segment revenue (GPU/AI) |
| **Q/Q HPC Growth** | 11 | Data cols | % | Sequential |
| **Y/Y HPC Growth** | 12 | Data cols | % | Year-over-year |
| **Internet of Things Revenue** | 13 | A + data cols | mm | Segment revenue |
| **Q/Q IoT Growth** | 14 | Data cols | % | Sequential |
| **Y/Y IoT Growth** | 15 | Data cols | % | Year-over-year |
| **Automotive Revenue** | 16 | A + data cols | mm | Segment revenue |
| **Q/Q Automotive Growth** | 17 | Data cols | % | Sequential |
| **Y/Y Automotive Growth** | 18 | Data cols | % | Year-over-year |
| **Digital Consumer Electronics Revenue** | 19 | A + data cols | mm | Segment revenue |
| **Q/Q DCE Growth** | 20 | Data cols | % | Sequential |
| **Y/Y DCE Growth** | 21 | Data cols | % | Year-over-year |
| **Other Revenue** | 22 | A + data cols | mm | Other segments |
| **Q/Q Other Growth** | 23 | Data cols | % | Sequential |
| **Y/Y Other Growth** | 24 | Data cols | % | Year-over-year |
| **Total Revenue** | 25 | A + data cols | mm | **KEY: Consolidated revenue** |
| **Q/Q Total Revenue Growth** | 27 | Data cols | % | Sequential growth |
| **Y/Y Total Revenue Growth** | 28 | Data cols | % | Year-over-year growth |
| **Consolidated Revenue in USD** | 30 | A + data cols | mm | Calculated |
| **Consolidated Revenue Reported** | 31 | A + data cols | mm | Reported by company |

**Note**: TSMC has 5 revenue segments: Smartphone, HPC, IoT, Automotive, Digital Consumer Electronics

### Key Profitability Metrics

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Operating Expense Section** | 33 | A | Header | Section divider |
| **Revenue (Reference)** | 34 | A + data cols | mm | Links to Total Revenue row 25 |
| **Gross Profit** | 36 | A + data cols | mm | Revenue - COGS |
| **Y/Y Gross Profit Growth** | 37 | Data cols | % | Year-over-year growth |
| **Gross Margin %** | 38 | A + data cols | % | **KEY: Profitability metric** |
| **Consensus Gross Margin %** | 39 | A + data cols | % | External consensus estimates |
| **Y/Y Gross Margin Improvement** | 40 | Data cols | bps | Basis points change |
| **R&D Expense** | 42 | A + data cols | mm | Research & Development |
| **Y/Y R&D Growth** | 43 | Data cols | % | Year-over-year growth |
| **R&D Margin %** | 44 | A + data cols | % | R&D / Revenue |
| **Y/Y R&D Margin Improvement** | 45 | Data cols | bps | Basis points change |
| **G&A Margin %** | 49 | A + data cols | % | General & Administrative |
| **Y/Y G&A Improvement** | 50 | Data cols | bps | Basis points change |
| **S&M Margin %** | 54 | A + data cols | % | Sales & Marketing |
| **Y/Y S&M Improvement** | 55 | Data cols | bps | Basis points change |
| **EBIT** | 59 | A + data cols | mm | **KEY: Operating profit** |
| **Y/Y EBIT Growth** | 60 | Data cols | % | Year-over-year growth |
| **EBIT Margin %** | 61 | A + data cols | % | EBIT / Revenue |
| **Y/Y EBIT Margin Improvement** | 62 | Data cols | bps | Basis points change |

### Key Cash Flow & Balance Sheet Items

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **D&A Breakdown Section** | 64 | A | Header | Section divider |
| **Depreciation - COGS** | 65 | A + data cols | mm | Part of COGS |
| **Depreciation - OpEx** | 66 | A + data cols | mm | Part of operating expense |
| **Depreciation - Other OpEx** | 67 | A + data cols | mm | Other depreciation |
| **Total Depreciation** | 68 | A + data cols | mm | Sum of above |
| **Depreciation - Right-of-Use Assets** | 70 | A + data cols | mm | Lease accounting (IFRS 16) |
| **Depreciation - PP&E (Calculated)** | 71 | A + data cols | mm | Plant, property, equipment |
| **Total Depreciation (Summary)** | 72 | A + data cols | mm | **KEY: For UFCF calculation** |
| **Amortization - COGS** | 74 | A + data cols | mm | Intangible amortization |
| **Amortization - OpEx** | 75 | A + data cols | mm | Intangible amortization in OpEx |
| **Total Amortization** | 76 | A + data cols | mm | Sum of above |
| **Net Revenue** | 80 | A + data cols | mm | Alternative revenue measure |
| **Net Income** | 82 | A + data cols | mm | **KEY: Net profit/loss** |
| **Earnings Per Share - WAD** | 83 | A + data cols | US$ | **KEY: EPS, diluted shares** |
| **Earnings Per ADR - WAD** | 84 | A + data cols | US$ | Per ADR (5 shares) |
| **CapEx** | 86 | A + data cols | bn | **KEY: Capital expenditure** |

### Working Capital & Balance Sheet Details

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Key Metrics Section** | 88+ | A | Headers | Multiple detail sections |
| **Process Node Revenue %** | 89-102 | A + data cols | % | Detailed technology node breakdown |
| **AI Processors Revenue** | 182-186 | A + data cols | mm, % | High-growth segment metric |

---

## 2. CoreWeave (CoreWeave CRWV US.xlsx)

### Model Dimensions
- **Dimensions**: A1:AV878 (878 rows × 48 columns)
- **Shorter history**: Newer company (IPO 2023)
- **More compressed structure** than TSMC/ASML

### Column Structure

| Metric | Columns | Description |
|--------|---------|-------------|
| **Historical FY** | C-N | Multiple historical years |
| **Recent Quarters** | O-R | Q1-Q4 recent fiscal year |
| **Next FY & Quarters** | S-W | Full year + quarterly breakdown |
| **Forecast Years** | X-AM+ | FY2025, FY2026, etc. |
| **Out Years** | AR-AU | Future annual years |

### Key Revenue Metrics

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Revenue Build Section** | 6 | A | Header | Section divider |
| **Total Revenue** | 7 | A + data cols | mm | **KEY: Only 1 total (no segments)** |
| **Q/Q Total Revenue Growth** | 9 | Data cols | % | Sequential growth |
| **Y/Y Total Revenue Growth** | 10 | Data cols | % | Year-over-year growth |

**Note**: CoreWeave reports revenue as single line, but provides:
- Committed Contracts vs On-Demand breakout (Row 170-172)
- Geographic breakdown (Row 133-135)
- Customer concentration data (Row 138+)

### Key Profitability Metrics (Mixed GAAP/Non-GAAP)

CoreWeave reports both GAAP and Non-GAAP metrics. For DCF, use **GAAP Operating Income**.

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Non-GAAP EBITDA** | 12 | A + data cols | mm | Company reported (addback D&A to Op Inc) |
| **Y/Y EBITDA Growth** | 14 | Data cols | % | Year-over-year |
| **Non-GAAP EBITDA Margin** | 15 | A + data cols | % | EBITDA / Revenue |
| **Y/Y EBITDA Margin Improvement** | 17 | Data cols | bps | Basis points change |
| **Company Reported Non-GAAP Op Income** | 19 | A + data cols | mm | Alternative operating profit |
| **Y/Y Op Income Growth** | 21 | Data cols | % | Year-over-year |
| **Non-GAAP Op Income Margin** | 22 | A + data cols | % | Op Inc / Revenue |
| **Non-GAAP Net Income** | 26 | A + data cols | mm | Non-GAAP net profit |
| **Y/Y Net Income Growth** | 27 | Data cols | % | Year-over-year |
| **Non-GAAP Net Income Margin** | 28 | A + data cols | % | Net Inc / Revenue |
| **Non-GAAP EPS - WAD** | 31 | A + data cols | USD/share | **KEY: Diluted shares outstanding** |
| **GAAP Gross Profit** | 42 | A + data cols | mm | **KEY: Revenue - COGS** |
| **Y/Y Gross Profit Growth** | 43 | Data cols | % | Year-over-year |
| **GAAP Gross Margin** | 44 | A + data cols | % | GAAP margin % |
| **Y/Y Gross Margin Improvement** | 45 | Data cols | bps | Basis points change |
| **SBC in COGS** | 48 | Data cols | % | Stock-based comp as % of revenue |
| **Amortization of Intangibles COGS** | 49 | A + data cols | mm | Intangible amortization |
| **Non-GAAP Gross Profit** | 51 | A + data cols | mm | Excl. SBC & amortization |
| **Non-GAAP Gross Margin** | 53 | A + data cols | % | **KEY: For DCF margin assumptions** |
| **GAAP R&D Expense** | 57 | A + data cols | mm | Research & Development |
| **Y/Y R&D Growth** | 58 | Data cols | % | Year-over-year |
| **GAAP R&D Margin** | 59 | A + data cols | % | R&D / Revenue |
| **Y/Y R&D Margin Improvement** | 60 | Data cols | bps | Basis points change |
| **SBC R&D** | 62 | A + data cols | mm | Stock-based comp in R&D |
| **SBC R&D %** | 63 | A + data cols | % | SBC / Revenue |
| **Amortization R&D** | 64 | A + data cols | mm | Intangible amortization |
| **Non-GAAP R&D Expense** | 66 | A + data cols | mm | R&D excl. SBC & amort |
| **Non-GAAP R&D Margin** | 68 | A + data cols | % | **KEY: For margin assumptions** |
| **GAAP S&M Margin** | 73 | A + data cols | % | Sales & Marketing / Revenue |
| **GAAP G&A Margin** | 87 | A + data cols | % | General & Admin / Revenue |
| **GAAP Operating Income** | 99 | A + data cols | mm | **KEY: GAAP Op Inc (use for DCF)** |
| **Y/Y Op Inc Growth** | 100 | Data cols | % | Year-over-year |
| **GAAP Op Income Margin** | 101 | A + data cols | % | Op Inc / Revenue |
| **Non-GAAP Operating Income** | 104 | A + data cols | mm | Non-GAAP version |

### Key Cash Flow Items

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Reported Depreciation** | 111 | A + data cols | mm | D&A addback |
| **Total D&A** | 129 | A + data cols | mm | **KEY: Depreciation + Amortization** |
| **Depreciation** | 127 | A + data cols | mm | D&A component |
| **Amortization** | 128 | A + data cols | mm | D&A component |
| **Free Cash Flow** | 182 | A + data cols | mm | **KEY: Operating FCF** |
| **LTM Free Cash Flow** | 183 | A + data cols | mm | Last 12 months FCF |
| **LTM Revenue** | 184 | A + data cols | mm | Last 12 months revenue |
| **LTM Revenue Growth** | 185 | Data cols | % | Year-over-year LTM growth |
| **LTM FCF Margin** | 186 | A + data cols | % | FCF / Revenue |
| **CapEx** | 216 | A + data cols | mm | **KEY: Capital expenditure** |

### Working Capital Details

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Operating Lease Payments** | 198-205 | A + data cols | mm | Future lease obligations (financing item) |
| **Operating Lease Liabilities** | 207-211 | A + data cols | mm | Present value of leases |
| **Revenue Granularity** | 219-225 | A + data cols | mm, % | Customer expansion metrics |
| **Cost Granularity** | 227-234 | A + data cols | mm, % | Rent, utilities, personnel, SBC, D&A breakdown |

---

## 3. ASML (ASML Holding ASML NA.xlsx)

### Model Dimensions
- **Dimensions**: A1:CC837 (837 rows × 81 columns)
- **Similar structure to TSMC** (both use same analyst template)
- **Strong historical data** from FY2009+

### Column Structure

**Identical to TSMC structure** – see TSMC section above.

### Key Revenue Metrics

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Revenue Build Section** | 6 | A | Header | More detailed breakdown than TSMC |
| **EUV Equipment Units** | 7-9 | A + data cols | units | EUV 3400C, 3400B, High NA breakdown |
| **Product-based Revenue Build** | 10-40 | A + data cols | mm | Built from unit volumes and prices |
| **Total Revenue** | 41 | A + data cols | mm | **KEY: Consolidated revenue** |
| **Y/Y Total Revenue Growth** | 51 | Data cols | % | Year-over-year growth |
| **Net Deferred Revenue** | 66 | A + data cols | mm | Fast shipment impact |
| **Normalized Revenue** | 67 | A + data cols | mm | Adjusted for deferred revenue |

**Note**: ASML has unique product-based revenue model (EUV tools are major driver)

### Key Profitability Metrics

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Operating Expense Section** | 69 | A | Header | Section divider |
| **Revenue (Reference)** | 70 | A + data cols | mm | Links to Total Revenue row 41 |
| **Gross Profit** | 72 | A + data cols | mm | Revenue - COGS |
| **Y/Y Gross Profit Growth** | 73 | Data cols | % | Year-over-year growth |
| **Gross Margin %** | 74 | A + data cols | % | **KEY: Profitability metric** |
| **Y/Y Gross Margin Improvement** | 76 | Data cols | bps | Basis points change |
| **R&D Expense** | 78 | A + data cols | mm | Research & Development |
| **Y/Y R&D Growth** | 79 | Data cols | % | Year-over-year growth |
| **R&D Margin %** | 80 | A + data cols | % | R&D / Revenue |
| **Y/Y R&D Margin Improvement** | 81 | Data cols | bps | Basis points change |
| **SG&A Margin %** | 85 | A + data cols | % | Sales, General, Administrative |
| **Y/Y SG&A Improvement** | 86 | Data cols | bps | Basis points change |
| **EBIT** | 89 | A + data cols | mm | **KEY: Operating profit** |
| **Y/Y EBIT Growth** | 91 | Data cols | % | Year-over-year growth |
| **EBIT Margin %** | 92 | A + data cols | % | EBIT / Revenue |
| **Y/Y EBIT Margin Improvement** | 94 | Data cols | bps | Basis points change |
| **EBITDA** | 98 | A + data cols | mm | EBIT + D&A |
| **Y/Y EBITDA Growth** | 99 | Data cols | % | Year-over-year growth |
| **EBITDA Margin %** | 100 | A + data cols | % | EBITDA / Revenue |
| **Y/Y EBITDA Margin Improvement** | 101 | Data cols | bps | Basis points change |
| **Add back: D&A** | 96 | A + data cols | mm | For EBITDA reconciliation |

### Key Cash Flow Items

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **D&A Breakdown Section** | 103 | A | Header | Section divider |
| **Depreciation - COGS** | 104 | A + data cols | mm | Part of COGS |
| **Depreciation - R&D** | 105 | A + data cols | mm | Part of R&D |
| **Depreciation - SG&A** | 106 | A + data cols | mm | Part of SG&A |
| **Depreciation of PP&E** | 107 | A + data cols | mm | Property, plant, equipment |
| **Amortization - COGS** | 108 | A + data cols | mm | Intangible amortization |
| **Amortization - R&D** | 109 | A + data cols | mm | Intangible amortization |
| **Amortization - SG&A** | 110 | A + data cols | mm | Intangible amortization |
| **Amortization of Intangibles** | 111 | A + data cols | mm | Total intangible amort |
| **Other D&A** | 112 | A + data cols | mm | Other depreciation/amortization |
| **Total D&A** | 113 | A + data cols | mm | **KEY: For UFCF calculation** |
| **Share-based Payments** | 251 | A + data cols | mm | SBC expense |

### Product & Customer Breakdown

| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| **Revenue by Bookings %** | 161-164 | A + data cols | % | Foundry, IDM, Logic, Memory |
| **Revenue Recognition %** | 191 | A + data cols | % | % of backlog converted to revenue |
| **Geographic Revenue** | 212-234 | A + data cols | mm, % | Japan, Korea, Singapore, Taiwan, China, etc. |

---

## COLUMN LETTER REFERENCE GUIDE

### TSMC & ASML (81 columns, C through AW)

**Historical Period**: C-G (typically FY2009-FY2013 or similar)

**FY2025 & FY2026 Region**:
```
Column | Period
-------+-------------------------------------------
   G   | FY2024 (or recent full year)
   H   | Q1-2025
   I   | Q2-2025
   J   | Q3-2025
   K   | Q4-2025
   L   | FY2025 (annual)
   M   | Q1-2026
   N   | Q2-2026
   O   | Q3-2026
   P   | Q4-2026
   Q   | FY2026 (annual)
```

**Out-Year Region** (FY2027-FY2030):
```
Column | Period
-------+-------------------------------------------
   R   | Q1-2027
   S   | Q2-2027
   T   | Q3-2027
   U   | Q4-2027
   V   | FY2027 (annual)
   W   | Q1-2028
   X   | Q2-2028
   Y   | Q3-2028
   Z   | Q4-2028
   AA  | FY2028 (annual)
   AB  | Q1-2029
   AC  | Q2-2029
   AD  | Q3-2029
   AE  | Q4-2029
   AF  | FY2029 (annual)
   AG  | Q1-2030
   AH  | Q2-2030
   AI  | Q3-2030
   AJ  | Q4-2030
   AK  | FY2030 (annual)
```

### CoreWeave (48 columns, C through AU)

**More compressed structure** due to fewer historical years:

```
Column | Period
-------+-------------------------------------------
   C   | FY2019 (or first historical year)
   ...
   N   | FY2024 (or recent)
   O   | Q1-2025
   P   | Q2-2025
   Q   | Q3-2025
   R   | Q4-2025
   S   | FY2025 (annual)
   T   | Q1-2026
   U   | Q2-2026
   V   | Q3-2026
   W   | Q4-2026
   X   | FY2026 (annual)
   Y   | Q1-2027
   Z   | Q2-2027
   AA  | Q3-2027
   AB  | Q4-2027
   AC  | FY2027 (annual)
```

---

## SUMMARY: KEY METRICS FOR DCF ENGINE

### Universal Key Rows (All Companies)

| Category | TSMC Row | CoreWeave Row | ASML Row | Notes |
|----------|----------|---------------|----------|-------|
| **Total Revenue** | 25 | 7 | 41 | **CRITICAL: Revenue input** |
| **Gross Margin %** | 38 | 44 (GAAP) | 74 | **CRITICAL: Margin driver** |
| **R&D Margin %** | 44 | 59 (GAAP) | 80 | **CRITICAL: Margin driver** |
| **SG&A Margin %** | 49-54 | 73, 87 | 85 | **CRITICAL: Margin driver** |
| **EBIT / Op Income** | 59 | 99 (GAAP) | 89 | **CRITICAL: Operating profit** |
| **Depreciation & Amortization** | 72 | 129 | 113 | **CRITICAL: D&A for UFCF** |
| **CapEx** | 86 | 216 | N/A (search) | **CRITICAL: Investment** |
| **Net Income** | 82 | 26 (Non-GAAP) | N/A (search) | For EPS calculation |
| **EPS (WAD)** | 83 | 31 (Non-GAAP) | N/A (search) | Shares outstanding |

### Column References for Recent/Forecast Period

**For FY2025-FY2030 DCF Projections:**
- **TSMC/ASML**: Columns L (FY2025), Q (FY2026), V (FY2027), AA (FY2028), AF (FY2029), AK (FY2030)
- **CoreWeave**: Columns S (FY2025), X (FY2026), AC (FY2027), AH (FY2028)

---

## IMPLEMENTATION NOTES FOR PYTHON DCF ENGINE

### 1. **Read Sequence**
1. Load Model sheet with `data_only=False` to access formulas
2. Read historical data from columns C-L (or appropriate range)
3. Extract period labels from Row 5 to identify column meanings
4. Map key metric rows to retrieve revenue, margins, D&A, CapEx

### 2. **Revenue Drivers** (Company-Specific)
- **TSMC**: Row 25 (Total) = Sum of rows 7, 10, 13, 16, 19, 22 (5 segments)
  - For scenario analysis: Adjust individual segment growth rates (rows 9, 12, 15, 18, 21, 24)
- **CoreWeave**: Row 7 (single total)
  - For scenario analysis: Adjust Y/Y growth (Row 10) or revenue by type (Rows 170-172)
- **ASML**: Row 41 (Total) = Sum of product-based build (rows ~7-40)
  - For scenario analysis: Adjust unit volumes and pricing

### 3. **Margin Drivers** (Company-Specific)
- **TSMC**:
  - Gross Margin: Row 38
  - R&D Margin: Row 44
  - SG&A/G&A/S&M: Rows 49-54
  - EBIT Margin: Row 61 (calculated)

- **CoreWeave**:
  - **Use GAAP, not Non-GAAP** for DCF:
    - Gross Margin: Row 44 (GAAP, incl. SBC & Amort)
    - R&D Margin: Row 59 (GAAP)
    - SG&A Margin: Row 87 (GAAP)
  - Operating Income: Row 99 (GAAP)

- **ASML**:
  - Gross Margin: Row 74
  - R&D Margin: Row 80
  - SG&A Margin: Row 85
  - EBIT Margin: Row 92 (calculated)

### 4. **Cash Flow Items**
- **D&A**: TSMC (Row 72), CoreWeave (Row 129), ASML (Row 113)
- **CapEx**: TSMC (Row 86 in billions), CoreWeave (Row 216), ASML (row to be determined)
- **Stock-based Comp (SBC)**:
  - TSMC: Included in opex margins
  - CoreWeave: Explicit rows (62, 48 for R&D and COGS)
  - ASML: Row 251

### 5. **Working Capital**
- **Not explicitly broken out** in summary rows
- Need to search for:
  - Accounts Receivable (AR)
  - Inventory
  - Accounts Payable (AP)
  - Or use approximation: WC = NWC % of Revenue (typically 5-15%)

### 6. **Balance Sheet for Terminal Value**
- **Shares Outstanding (Diluted)**: Derive from EPS rows
  - TSMC Row 83 (EPS) → Calculate: Net Income (Row 82) / EPS = Shares
  - CoreWeave Row 31 (Non-GAAP EPS)
- **Debt**: Search for "debt" or "borrowing" in balance sheet section
- **Cash**: Search for "cash" in balance sheet section

### 7. **Period Mapping for Formulas**
Use Row 5 to dynamically determine column meaning:
```python
# Pseudocode
for col_idx in range(3, ws.max_column):
    period_label = ws.cell(5, col_idx).value
    if "FY2025" in str(period_label):
        fy2025_col = get_column_letter(col_idx)
    elif "Q1" in str(period_label) and "2026" in str(period_label):
        q1_2026_col = get_column_letter(col_idx)
    # ... etc
```

---

## NEXT STEPS

1. **Create Python classes** for each company model:
   - `TSMCDCFEngine(file_path)`
   - `CoreWeaveDCFEngine(file_path)`
   - `ASMLDCFEngine(file_path)`

2. **Implement read methods** that use the row/column mappings above

3. **Build DCF tab** in Excel using openpyxl, mirroring NVIDIA structure

4. **Create PM agent interface** with key drivers:
   - Revenue growth assumptions
   - Margin improvement assumptions (GM bps, R&D bps, SG&A bps)
   - CapEx % of revenue
   - NWC % of revenue

5. **Map company-specific levers** to consistent DCF variables

---

## APPENDIX: Full Cell Directory

### TSMC Model Rows 1-150

**Metric Categories:**
- Rows 1-5: Headers and metadata
- Rows 6-31: Revenue Build (5 segments + total)
- Rows 33-62: Operating Expense & Profitability
- Rows 64-86: D&A, CapEx, EPS
- Rows 88-300+: Detailed segmentation by product, geography, customer

### CoreWeave Model Rows 1-250

**Metric Categories:**
- Rows 1-5: Headers and metadata
- Rows 6-31: Revenue, EBITDA, Operating Income, Net Income (all with margins)
- Rows 39-130: Operating expense detail (GAAP vs Non-GAAP breakdown)
- Rows 132-216: Geographic, customer, revenue type breakdowns, CapEx
- Rows 259-294: Margin analysis summaries

### ASML Model Rows 1-250

**Metric Categories:**
- Rows 1-5: Headers and metadata
- Rows 6-67: Revenue Build (product-based from units)
- Rows 69-113: Operating Expense & D&A
- Rows 161-251: Product type, geography, bookings detail, employee counts

---

## FILE PATHS

```
TSMC:     /Users/matthewwolfman/Documents/CS372_Assignment3/agent-alpha/financial_models/Taiwan Semiconductor Manufacturing Company TSM US.xlsx
CoreWeave: /Users/matthewwolfman/Documents/CS372_Assignment3/agent-alpha/financial_models/CoreWeave CRWV US.xlsx
ASML:     /Users/matthewwolfman/Documents/CS372_Assignment3/agent-alpha/financial_models/ASML Holding ASML NA.xlsx
```

---

**Analysis completed**: February 17, 2026
