# DCF Cell Mapping Analysis - Complete Reference

**Analysis Date:** February 17, 2026
**Companies:** TSMC, CoreWeave, ASML
**Purpose:** Identify all key cells for DCF analysis and Python engine development

---

## Overview

This analysis identifies **all critical financial cells** in three analyst models used for DCF valuation. Each document serves a different purpose:

### Document Structure

| Document | Format | Purpose | Audience |
|----------|--------|---------|----------|
| **DCF_CELL_MAPPING.md** | Markdown | Comprehensive reference with detailed explanations | Developers building DCF engines |
| **KEY_CELL_REFERENCE.txt** | Text tables | Quick lookup format, side-by-side company comparison | Quick daily reference |
| **DCF_IMPLEMENTATION_GUIDE.py** | Python | Pseudocode, methods, data extraction patterns | Python developers |
| **DCF_ANALYSIS_SUMMARY.txt** | Text | Executive summary, findings, next steps | Project managers, leads |

---

## Quick Start: Which Document to Use?

### "I need to find where Total Revenue is in TSMC model"
→ **KEY_CELL_REFERENCE.txt** - Section 1 (Revenue & Growth)

### "I need to implement a Python method to extract D&A from all three companies"
→ **DCF_IMPLEMENTATION_GUIDE.py** - Section 4 (Extraction Methods)

### "I need to understand why CoreWeave metrics are different from TSMC"
→ **DCF_CELL_MAPPING.md** - Company-specific sections with detailed notes

### "I need to set up project tasks and implementation phases"
→ **DCF_ANALYSIS_SUMMARY.txt** - Section "Next Steps for Development"

### "I need to understand the column structure for FY2026 forecasts"
→ **KEY_CELL_REFERENCE.txt** - Section 5 (Column Structure) or DCF_CELL_MAPPING.md

---

## Key Metrics Summary

All three companies' financial models contain the same **essential DCF metrics**, but at different row numbers:

### Universal Rows by Metric Type

```
REVENUE:
  TSMC      → Row 25
  CoreWeave → Row 7
  ASML      → Row 41

GROSS MARGIN %:
  TSMC      → Row 38
  CoreWeave → Row 44 (GAAP)
  ASML      → Row 74

OPERATING INCOME (EBIT):
  TSMC      → Row 59
  CoreWeave → Row 99 (GAAP)
  ASML      → Row 89

DEPRECIATION & AMORTIZATION:
  TSMC      → Row 72 + 76
  CoreWeave → Row 129
  ASML      → Row 113

CAPEX:
  TSMC      → Row 86 (in billions)
  CoreWeave → Row 216
  ASML      → (requires search)
```

### Column References (FY2025-FY2030)

```
FY2025: TSMC/ASML=L    CoreWeave=S
FY2026: TSMC/ASML=Q    CoreWeave=X
FY2027: TSMC/ASML=V    CoreWeave=AC
FY2028: TSMC/ASML=AA   CoreWeave=AH
FY2029: TSMC/ASML=AF   CoreWeave=AM
FY2030: TSMC/ASML=AK   CoreWeave=(limited)
```

---

## Critical Implementation Notes

### 1. CoreWeave Metric Selection
CoreWeave reports **both GAAP and Non-GAAP** metrics. **For DCF, always use GAAP:**
- Gross Margin: Row 44 (not Row 53)
- R&D Margin: Row 59 (not Row 68)
- Operating Income: Row 99 (not Row 104)

### 2. TSMC CapEx Unit Conversion
- Row 86 is in **billions**, not millions
- Convert: CapEx(mm) = CapEx(bn) × 1000

### 3. Dynamic Period Detection
Period labels in Row 5 are formula-driven. Use this pattern:
```python
for col_idx in range(3, ws.max_column + 1):
    label = ws.cell(5, col_idx).value
    if "FY2026" in str(label):
        return get_column_letter(col_idx)  # Returns "Q"
```

### 4. Working Capital Approximation
- Not explicitly broken out in models
- Recommend: NWC = 10-15% of Revenue
- Or: Search rows 250+ for balance sheet items (AR, Inventory, AP)

### 5. Margin Improvement Basis Points
Cascade margins period-over-period for scenario analysis:
```
New Margin = Old Margin + (Improvement bps / 10,000)
Example: 50% + (200 bps / 10,000) = 50% + 0.02% = 50.02%
```

---

## File Structure

### Document 1: DCF_CELL_MAPPING.md (23 KB)

**Complete reference guide - use for detailed lookups**

Sections:
1. Executive Summary - high-level overview
2. TSMC Analysis - 50+ key cells documented
3. CoreWeave Analysis - 40+ key cells documented
4. ASML Analysis - 40+ key cells documented
5. Column Letter Reference Guide - mapping for all 81/48 columns
6. Summary: Key Metrics for DCF Engine - consolidated tables
7. Implementation Notes for Python DCF Engine
8. Appendix: Full Cell Directory by row ranges

Example reference:
```
| Metric | Row | Column(s) | Type | Notes |
|--------|-----|-----------|------|-------|
| Total Revenue | 25 | A + data cols | mm | KEY: Consolidated revenue |
| Gross Margin % | 38 | A + data cols | % | KEY: Profitability metric |
| EBIT | 59 | A + data cols | mm | KEY: Operating profit |
```

### Document 2: KEY_CELL_REFERENCE.txt (11 KB)

**Quick lookup tables - use for daily reference**

Sections:
1. Revenue & Growth - 3-column comparison table
2. Profitability Metrics - margin rows by company
3. Cash Flow Items - D&A, CapEx, SBC, WC
4. Shares Outstanding & Valuation - EPS and stock price
5. Column Structure for Projections - period-to-column mappings
6. Period Labels (Row 5) - how to identify periods dynamically
7. Margin Improvement Drivers - basis point calculations
8. Usage Examples for DCF Engine - real-world code snippets
9. File Paths - full paths to all three Excel files
10. Validation Checks - data quality sanity checks

Example usage:
```
Q: Where is Total Revenue for TSMC?
A: Row 25, all data columns (Column L for FY2025, Q for FY2026, etc.)

Q: What's the column for Q2-2026?
A: Column N (TSMC/ASML), Column U (CoreWeave)
```

### Document 3: DCF_IMPLEMENTATION_GUIDE.py (22 KB)

**Python code patterns and pseudocode - use for development**

Sections:
1. Universal Constants - header rows, column indices
2. Company-Specific Row Mappings - Python dictionaries
3. Column Structure Mappings - functions for period-to-column lookup
4. Extraction Methods - pseudocode for data retrieval
5. DCF Building Blocks - UFCF calculation formulas
6. Validation & Error Handling - data quality checks
7. Example Usage - commented code samples

Code pattern example:
```python
TSMC_ROWS = {
    'total_revenue': 25,
    'gross_margin_pct': 38,
    'ebit': 59,
    'total_depreciation': 72,
    'capex_bn': 86,
}

def extract_revenue(ws, col_letter):
    return ws[f"{col_letter}{TSMC_ROWS['total_revenue']}"].value
```

### Document 4: DCF_ANALYSIS_SUMMARY.txt (11 KB)

**Executive summary and project planning - use for alignment**

Sections:
1. Analysis Completed - deliverables overview
2. Key Findings - company characteristics
3. Critical Metrics for DCF Engine - consolidated row/column references
4. Special Cases & Gotchas - 6 important notes
5. Implementation Recommendations - 6 action items
6. Data Quality Notes - strengths, gaps, recommendations
7. Next Steps for Development - 4 implementation phases with checklists
8. Files Delivered - project deliverables list
9. Analysis Completion Status - completion percentage by category

Example finding:
```
TSMC (81 columns, 1,106 rows):
  - 5 revenue segments: Smartphone, HPC, IoT, Automotive, Digital Consumer
  - Key rows: Revenue=25, GM=38, EBIT=59, D&A=72, CapEx=86
  - All metrics follow GAAP basis
```

---

## How to Use These Documents

### Scenario 1: Building a Python DCF Engine

**Step 1:** Read DCF_IMPLEMENTATION_GUIDE.py Section 2 (Row Mappings)
→ Creates Python dictionaries for metric row numbers

**Step 2:** Implement extraction methods from Section 4
→ Creates methods like `extract_revenue()`, `extract_margins()`

**Step 3:** Test with KEY_CELL_REFERENCE.txt validation checks
→ Ensures data quality (margins 0-100%, revenue > 0, etc.)

**Step 4:** Refer to DCF_CELL_MAPPING.md for complex metrics
→ Notes on margin improvements, D&A combinations, unit conversions

### Scenario 2: Creating a DCF Tab in Excel

**Step 1:** Use DCF_ANALYSIS_SUMMARY.txt Section "Implementation Recommendations"
→ Item 5: Create DCF tab (Rows 9-61, mirrors NVIDIA structure)

**Step 2:** Reference KEY_CELL_REFERENCE.txt Section 6-7
→ Period labels and margin improvement calculations

**Step 3:** Check DCF_CELL_MAPPING.md for company-specific detail
→ CoreWeave uses GAAP (not Non-GAAP), TSMC CapEx in billions

**Step 4:** Implement formulas linking to Model tab
→ Example: `=Model!L25` for FY2025 Total Revenue (TSMC)

### Scenario 3: PM Agent Interface Design

**Step 1:** Review DCF_ANALYSIS_SUMMARY.txt Section "Implementation Recommendations" Item 6
→ Lists 8 key drivers per company

**Step 2:** Validate driver ranges using KEY_CELL_REFERENCE.txt
→ Ensures growth rates and margin improvements are reasonable

**Step 3:** Reference historical values from DCF_CELL_MAPPING.md
→ Provides context (e.g., "Historical TSMC HPC growth: 50-100%")

**Step 4:** Implement PM interface with validation layer
→ Prevents invalid requests (negative growth, margin > 100%, etc.)

---

## Company-Specific Notes

### TSMC
- **Structure:** Mature, multi-segment semiconductor foundry
- **Revenue:** 5 segments (Smartphone, HPC, IoT, Automotive, Digital Consumer)
- **Key Metric Rows:** 25 (Revenue), 38 (GM), 59 (EBIT), 72+76 (D&A), 86 (CapEx)
- **Special Note:** CapEx in billions (row 86) - convert to millions
- **Process Detail:** Includes technology node breakdown (3nm, 5nm, etc.)

### CoreWeave
- **Structure:** Newer cloud infrastructure company (IPO 2023)
- **Revenue:** Single consolidated line (smaller than TSMC/ASML)
- **Key Metric Rows:** 7 (Revenue), 44 (GM), 99 (Op Inc), 129 (D&A), 216 (CapEx)
- **Special Note:** Reports GAAP and Non-GAAP - always use GAAP for DCF
- **FCF Detail:** Extensive free cash flow metrics (row 182, 183, 186)
- **Revenue Types:** Committed Contracts vs. On-Demand (rows 170-172)

### ASML
- **Structure:** Equipment manufacturer for semiconductor industry
- **Revenue:** Product-based model (units × price)
- **Key Metric Rows:** 41 (Revenue), 74 (GM), 89 (EBIT), 113 (D&A)
- **Special Note:** Uses "Normalized Revenue" (row 67) to adjust for deferred revenue
- **Product Detail:** EUV equipment (3400C, 3400B, High NA) volume tracking
- **Geographic:** Regional breakdown by customer location

---

## Data Validation Checklist

Before using extracted data, verify:

- [ ] Revenue > 0
- [ ] Margins are between 0% and 100%
- [ ] D&A < Revenue (typically 5-15%)
- [ ] CapEx < Revenue (typically 5-30%)
- [ ] Segment revenues sum to total (if applicable)
- [ ] Period labels in Row 5 are chronological
- [ ] Column dates in Row 4 are sequential
- [ ] EPS × Shares = Net Income (within rounding)

---

## File Paths

```
Model Files:
  /Users/matthewwolfman/Documents/CS372_Assignment3/agent-alpha/financial_models/
    ├── Taiwan Semiconductor Manufacturing Company TSM US.xlsx
    ├── CoreWeave CRWV US.xlsx
    └── ASML Holding ASML NA.xlsx

Reference Documents:
  /Users/matthewwolfman/Documents/CS372_Assignment3/agent-alpha/
    ├── DCF_CELL_MAPPING.md
    ├── KEY_CELL_REFERENCE.txt
    ├── DCF_IMPLEMENTATION_GUIDE.py
    ├── DCF_ANALYSIS_SUMMARY.txt
    └── README_DCF_ANALYSIS.md (this file)
```

---

## Next Steps

### Immediate (Week 1)
1. Review DCF_CELL_MAPPING.md Section 2-4 (company-specific mappings)
2. Create Python classes for metric extraction (use DCF_IMPLEMENTATION_GUIDE.py)
3. Test extraction on historical data (FY2024, FY2025)

### Short-term (Week 2-3)
1. Build DCF calculation engine (UFCF, Terminal Value, Valuation)
2. Create Excel DCF tab for each company
3. Implement PM agent interface with 8 key drivers

### Medium-term (Week 4)
1. Integration testing across all three companies
2. Sensitivity analysis on key DCF drivers
3. Multi-agent debate simulation (stock price impact)

---

## Questions & Support

| Question | Answer Location |
|----------|-----------------|
| Where is [Metric] in [Company]? | KEY_CELL_REFERENCE.txt, Sections 1-4 |
| How do I extract [Metric]? | DCF_IMPLEMENTATION_GUIDE.py, Section 4 |
| What's the column for FY2026? | KEY_CELL_REFERENCE.txt, Section 5 or DCF_CELL_MAPPING.md |
| What's different about CoreWeave? | DCF_CELL_MAPPING.md, CoreWeave section |
| What are the gotchas? | DCF_ANALYSIS_SUMMARY.txt, Section "Special Cases & Gotchas" |
| What's the project plan? | DCF_ANALYSIS_SUMMARY.txt, Section "Next Steps for Development" |

---

## Analysis Metadata

| Attribute | Value |
|-----------|-------|
| Analysis Date | February 17, 2026 |
| Analyst | Claude Code, CS372 Agent Alpha |
| Companies Analyzed | TSMC, CoreWeave, ASML |
| Total Metrics Catalogued | 100+ |
| Excel Sheets Analyzed | 6+ (Model sheets + Support sheets) |
| Lines of Reference Material | 1500+ |
| Total Documentation | ~70 KB |

---

**Status:** Analysis Complete - Ready for Implementation

**Last Updated:** 2026-02-17

**Version:** 1.0
