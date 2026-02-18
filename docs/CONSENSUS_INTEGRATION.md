# Consensus Estimates Integration

## Overview

Company analysts can now read consensus estimates from Excel files, compare them to their own model assumptions, and use this understanding as input to thesis development.

## Architecture

### 1. Consensus Reader (`tools/consensus_reader.py`)

Reads and parses consensus estimates from Excel files:

```python
from tools.consensus_reader import ConsensusReader

reader = ConsensusReader('NVDA')
consensus = reader.get_consensus()

# Get annual consensus for specific years
annual = reader.get_annual_consensus(['FY2026', 'FY2027', 'FY2028'])
```

**Data Structure:**
- Revenue (total and by segment)
- Margins (gross income, operating income, EBITDA)
- OpEx (R&D, SG&A)
- EPS (GAAP and Non-GAAP)

### 2. Company Analyst Integration

New methods in `CompanyAnalystAgent`:

#### `understand_consensus()` → dict
Reads consensus and compares to own model:

```python
analyst = CompanyAnalystAgent('NVDA')
result = analyst.understand_consensus()

# Returns:
{
    'consensus': {...},      # Raw consensus data
    'own_model': {...},      # Own model forecasts
    'differences': {...},    # Key differences by fiscal year
    'summary': str,          # Text summary
}
```

#### `_get_own_model_forecasts()` → dict
Extracts forecasts from DCF engine:
- Loads appropriate engine (NVDA, CDNS, TSM, ASML, CRWV)
- Computes baseline valuation
- Returns standardized forecast structure

#### `_compare_to_consensus()` → dict
Identifies material differences:
- Revenue: >5% difference is material
- Operating income: >5% difference is material
- Operating margin: >100bps difference is material
- Segments: >10% difference is material

#### `_summarize_consensus_differences()` → str
Generates readable text summary of differences.

### 3. Thesis Development Integration

The `develop_thesis()` method now:
1. Calls `understand_consensus()` first
2. Passes consensus comparison to `_identify_thesis_points()`
3. Includes consensus context in LLM prompt

**Example workflow:**
```python
analyst = CompanyAnalystAgent('NVDA')

# Develop thesis with consensus understanding
thesis = analyst.develop_thesis(mode='contrarian')

# Thesis points will explain where model differs from consensus
# and why those differences are justified
```

## File Structure

```
Consensus estimates/
└── NVDA Feb 17 2025.xlsx   # Consensus estimates for NVDA
    ├── Row 3: Period headers (Jan '24, Jan '25, Apr '25, etc.)
    ├── Row 4: Quarter labels (Q1, Q2, Q3, Q4)
    ├── Row 5-16: EPS data
    ├── Row 17-26: Revenue by segment
    ├── Row 37-59: Margin and OpEx data
    └── ...
```

## Excel File Format

Consensus files must follow this structure:

- **Sheet name**: `{TICKER}-US` (e.g., "NVDA-US")
- **Row 3**: Period headers (e.g., "Jan '26E", "Jan '27E")
- **Row 4**: Quarter labels (e.g., "Q1  ", "Q2  ") for quarterly columns
- **Key rows**:
  - Row 17: Sales (total revenue)
  - Row 19: Data Center segment
  - Row 22: Gaming segment
  - Row 23: Professional Visualization
  - Row 24: Automotive
  - Row 25: OEM & Other
  - Row 44: Gross Income
  - Row 55: Operating Income
  - Row 51: EBITDA
  - Row 50: R&D expense
  - Row 47: SG&A expense

## Usage Examples

### Example 1: Check Consensus Understanding

```python
from agents.company_analyst_agent import CompanyAnalystAgent

analyst = CompanyAnalystAgent('NVDA')
result = analyst.understand_consensus()

print(result['summary'])
# Output:
# Consensus Comparison for NVDA
# ============================================================
#
# FY2026:
#   Op Income: BELOW consensus by -98.8% ($1,553M vs $133,924M)
#   Op Margin: BELOW consensus by -6202bps (0.7% vs 62.8%)
#
# FY2027:
#   Revenue: BELOW consensus by -11.0% ($294,100M vs $330,604M)
#   Op Income: BELOW consensus by -73.6% ($58,173M vs $220,139M)
#   ...
```

### Example 2: Develop Thesis with Consensus Context

```python
analyst = CompanyAnalystAgent('NVDA')

# This will automatically include consensus comparison
thesis = analyst.develop_thesis(mode='contrarian')

# Thesis points will be informed by consensus differences
for point in thesis['thesis_points']:
    print(f"\n{point['thesis']}")
    print(f"Direction: {point['direction']}")
    print(f"Consensus view: {point['consensus_view']}")
    print(f"Our view: {point['our_view']}")
```

### Example 3: Standalone Consensus Reader

```python
from tools.consensus_reader import ConsensusReader

reader = ConsensusReader('NVDA')
reader.print_summary()

# Get specific periods
annual = reader.get_annual_consensus(['FY2026', 'FY2027'])
fy26_revenue = annual['revenue']['FY2026']
fy26_datacenter = annual['segments']['datacenter']['FY2026']
```

## Testing

Run the test script:

```bash
python3 test_consensus.py NVDA
```

This will:
1. Read NVDA consensus estimates
2. Compare to own model
3. Print detailed differences
4. Demonstrate thesis integration

## Adding New Tickers

To add consensus estimates for a new ticker:

1. Place Excel file in `Consensus estimates/` folder
2. Name format: `{TICKER} {Date}.xlsx` (e.g., "CDNS Feb 17 2025.xlsx")
3. Ensure sheet name is `{TICKER}-US`
4. Follow the row structure documented above

The ConsensusReader will automatically find and parse the file.

## Materiality Thresholds

The comparison logic flags differences as "material" if they exceed:

| Metric | Threshold |
|--------|-----------|
| Revenue | >5% difference |
| Operating Income | >5% difference |
| Operating Margin | >100bps difference |
| Segment Revenue | >10% difference |

These thresholds can be adjusted in `_compare_to_consensus()` method.

## Benefits

1. **Thesis Development**: Analysts can generate thesis points that explain where and why their view differs from consensus

2. **Model Calibration**: Identify if model assumptions are significantly different from Street expectations

3. **Risk Management**: Understand consensus positioning to assess potential for surprises

4. **Debate Preparation**: Know where your view is contrarian vs consensus before debates

## Future Enhancements

Potential improvements:
- [ ] Add consensus estimate ranges (high/low/mean)
- [ ] Track consensus changes over time
- [ ] Add consensus revisions analysis
- [ ] Support for quarterly consensus comparisons
- [ ] Automated consensus updates from data providers
- [ ] Historical consensus accuracy tracking
