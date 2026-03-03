# Deep Thesis Support Engine

## Overview

The **Thesis Support Engine** provides comprehensive, multi-faceted analysis to validate and strengthen investment thesis points. Unlike the basic thesis development (which conducts 1-3 quick analyses), the deep support engine performs exhaustive investigation with quantitative evidence, risk assessment, and dynamic conviction scoring.

## Architecture

### ThesisSupport Class (`agents/thesis_support.py`)

```python
from agents.thesis_support import ThesisSupport, support_thesis_point

# Method 1: Via class
analyst = CompanyAnalystAgent('NVDA')
support = ThesisSupport('NVDA', analyst)
result = support.support_thesis_point(thesis_point, depth='deep')

# Method 2: Convenience function
result = support_thesis_point('NVDA', thesis_point, depth='deep')
```

### Depth Levels

| Level | Analyses | Use Case |
|-------|----------|----------|
| **quick** | 3 | Fast validation during thesis generation |
| **deep** | 5 | Standard deep dive on promising thesis |
| **exhaustive** | 7+ | Full diligence before position sizing |

## Workflow (7 Steps)

### Step 1: Expand Key Questions
- Start with 3 base questions from thesis point
- Use LLM to generate additional analytical questions
- Focus areas: quantitative metrics, competitive dynamics, customer behavior, financial impact, risks

**Example Expansion:**
```
Base questions (3):
1. What are the latest trends in AI adoption across industries?
2. How are cloud service providers planning to expand their infrastructure?
3. What is NVIDIA's competitive position in the AI accelerator market?

Added questions (2):
4. What are the projected growth rates for AI-related workloads in datacenters?
5. How is NVIDIA's pricing strategy for AI accelerators evolving?
```

### Step 2: Conduct Deep Analyses
For each question, gather evidence from **4 sources**:
1. **Company News** - Latest headlines, SEC filings
2. **Specialist Input** - Macro analyst, sector specialist views
3. **Consensus Data** - Comparison to Street expectations
4. **Market Data** - Valuation metrics, trading multiples

**Output per Analysis:**
```json
{
  "question": "What are the latest trends in AI adoption?",
  "analysis_type": "demand",
  "finding": "Strong trend in AI adoption, evidenced by $2B Yotta investment",
  "evidence_summary": "Multiple data centers launching, hyperscaler capex up 40%",
  "confidence": 0.7,
  "data_points": [
    "Semiconductor sector +25.0% in 3 months",
    "FY2027 datacenter revenue 11% below consensus"
  ],
  "supports_thesis": true,
  "strength": "moderate"
}
```

### Step 3: Gather Quantitative Evidence
Extract and categorize specific data points:
- **Growth rates** - CAGRs, Y/Y growth, QoQ trends
- **Market sizes** - TAM, SAM, addressable market estimates
- **Margin impacts** - Basis point changes, operating leverage
- **Competitive metrics** - Market share, win rates, pricing

**Example Output:**
```
Quantitative Evidence (10 data points):
- Semiconductor sector +25.0% in 3 months
- NVIDIA's FY2027 revenue 11.0% below consensus
- Datacenter segment growing at 40%+ CAGR
- Cloud capex expected to reach $300B by 2027
- NVIDIA holds 90%+ share of AI accelerator market
```

### Step 4: Identify Risks & Counterarguments
Analyze refuting evidence and identify potential weaknesses:

```json
{
  "risks": [
    {
      "risk": "Lack of clarity on cloud providers' expansion plans",
      "severity": "high",
      "probability": 0.4,
      "mitigation": "Yotta partnership signals continued investment"
    },
    {
      "risk": "Potential pricing pressure from AMD/Intel competition",
      "severity": "medium",
      "probability": 0.3,
      "mitigation": "CUDA moat provides pricing power"
    }
  ]
}
```

### Step 5: Assess Conviction
Dynamic conviction scoring based on evidence quality:

**Formula:**
```
support_score = Σ(confidence of supporting analyses) / total_analyses
refute_score = Σ(confidence of refuting analyses) / total_analyses
quant_strength = min(1.0, num_data_points / 10)
risk_penalty = num_high_severity_risks × 0.1

evidence_strength = (support_score - refute_score + quant_strength) / 2
final_conviction = initial_conviction + evidence_strength - risk_penalty
```

**Example:**
```
Initial conviction: 80%
Supporting analyses: 3 (avg confidence 70%)
Refuting analyses: 2 (avg confidence 30%)
Data points: 10 (strength = 100%)
High-severity risks: 1 (penalty = 10%)

support_score = 3×0.7/5 = 0.42
refute_score = 2×0.3/5 = 0.12
evidence_strength = (0.42 - 0.12 + 1.0) / 2 = 0.65
final_conviction = 0.80 + 0.65 - 0.10 = 0.95 (95%)

Conviction increased +15%!
```

### Step 6: Quantify DCF Implications
Translate thesis into specific driver changes, scaled by conviction:

```python
# Base driver change from thesis
datacenter_growth_FY2028 = 0.42  # 42% growth

# Conviction multiplier
conviction_multiplier = final_conviction / initial_conviction
                      = 0.95 / 0.80 = 1.1875

# Adjusted driver (more aggressive due to higher conviction)
adjusted_growth = baseline + (change × multiplier)
                = 0.35 + (0.07 × 1.1875)
                = 0.4331  # 43.3% growth
```

### Step 7: Generate Summary
Comprehensive markdown summary with:
- Conviction trajectory
- Evidence breakdown
- Risk assessment
- DCF implications
- Recommendation

## Real Example: NVDA Datacenter Thesis

### Input Thesis
```
Thesis: NVIDIA's datacenter growth will significantly outperform
        consensus expectations due to underestimated AI adoption
Direction: Bullish
Initial Conviction: 80%
```

### Output After Deep Support

**Conviction Assessment:**
- Initial: 80%
- Final: 95% (+15%)
- Rationale: 3 supporting analyses, 10 quantitative data points, 1 high-risk identified

**Analyses Conducted (5):**
1. ✓ AI adoption trends (70% confidence) - **Supports thesis**
2. ✗ Cloud infrastructure expansion (30% confidence) - Refutes thesis
3. ✓ NVIDIA competitive position (70% confidence) - **Supports thesis**
4. ✓ AI workload growth rates (70% confidence) - **Supports thesis**
5. ✗ Pricing strategy evolution (60% confidence) - Refutes thesis

**Quantitative Evidence:**
- Semiconductor sector +25% in 3 months (uptrend)
- FY2027 revenue 11% below consensus (conservative model)
- Datacenter segment growing 40%+ CAGR
- NVIDIA holds 90%+ AI accelerator market share
- $2B Yotta AI hub investment using NVIDIA chips

**Key Risks:**
- HIGH: Lack of clarity on cloud expansion plans (40% probability)
- MEDIUM: Pricing pressure from AMD/Intel (30% probability)
- MEDIUM: Overestimation of AI adoption (25% probability)

**DCF Impact:**
```
datacenter_growth:
  FY2028: 0.4331 (43.3% growth)
  vs baseline: 0.35 (35%)
  vs initial thesis: 0.42 (42%)

Adjusted upward by 1.19x due to increased conviction
```

## Comparison: Basic vs Deep Support

| Aspect | Basic (thesis development) | Deep Support |
|--------|---------------------------|--------------|
| **Analyses** | 3 (1 per key question) | 5-7 (expanded questions) |
| **Evidence sources** | 2 (news + specialist) | 4 (news + specialist + consensus + market) |
| **Quantitative data** | Extracted ad-hoc | Structured categorization |
| **Risk assessment** | None | Systematic risk identification |
| **Conviction scoring** | Static | Dynamic based on evidence |
| **DCF scaling** | Fixed | Scaled by conviction multiplier |
| **Runtime** | ~30 seconds | ~2 minutes |

## Usage Patterns

### Pattern 1: During Thesis Development
```python
# Generate thesis points
thesis = analyst.develop_thesis(mode='contrarian')

# Pick most promising thesis point
promising_thesis = thesis['thesis_points'][0]

# Deep dive on it
from agents.thesis_support import support_thesis_point
deep_result = support_thesis_point('NVDA', promising_thesis, depth='deep')

# Conviction increased? Proceed with position
if deep_result['conviction_assessment']['final_conviction'] > 0.8:
    print("High conviction - recommend large position")
```

### Pattern 2: Before Position Sizing
```python
# PM agent evaluating position size
for thesis_point in all_thesis_points:
    support_result = support_thesis_point(ticker, thesis_point, depth='exhaustive')

    final_conviction = support_result['conviction_assessment']['final_conviction']

    if final_conviction > 0.9:
        position_size = 0.30  # Max 30%
    elif final_conviction > 0.7:
        position_size = 0.15  # Moderate 15%
    else:
        position_size = 0.05  # Small 5%
```

### Pattern 3: Periodic Re-validation
```python
# Monthly: Re-run deep support on existing positions
for position in portfolio:
    thesis_point = position.original_thesis

    # Re-validate with fresh data
    updated_support = support_thesis_point(
        position.ticker,
        thesis_point,
        depth='deep'
    )

    conviction_change = (
        updated_support['conviction_assessment']['final_conviction'] -
        updated_support['conviction_assessment']['initial_conviction']
    )

    if conviction_change < -0.2:
        print(f"Conviction dropped 20%+ - consider trimming {position.ticker}")
```

## Output Files

Results saved to `data/analyst_views/{TICKER}_thesis_point{N}_deep_support.json`:

```json
{
  "timestamp": "2026-02-17T22:17:55.807127",
  "thesis_point": {...},
  "analyses": [...],
  "quantitative_evidence": {
    "data_points": [...],
    "growth_rates": [...],
    "market_sizes": [...],
    "margin_impacts": [...],
    "competitive_metrics": [...]
  },
  "risks_counterarguments": [...],
  "conviction_assessment": {
    "initial_conviction": 0.80,
    "final_conviction": 0.95,
    "change": 0.15,
    "evidence_strength": 0.65,
    "rationale": "..."
  },
  "dcf_implications": {
    "driver_changes": {...},
    "conviction": 0.95,
    "adjustment_note": "Scaled by 1.19x conviction multiplier"
  },
  "summary": "..."
}
```

## Benefits

1. **More Rigorous Analysis**
   - 4 evidence sources vs 2
   - 5-7 analyses vs 3
   - Quantitative data extraction
   - Systematic risk assessment

2. **Dynamic Conviction**
   - Adjusts based on evidence quality
   - Accounts for refuting analyses
   - Penalizes for high-severity risks
   - Provides clear rationale

3. **Better DCF Integration**
   - Scales driver changes by conviction
   - Higher conviction = more aggressive positioning
   - Lower conviction = more conservative

4. **Audit Trail**
   - Comprehensive JSON output
   - All evidence sources documented
   - Risk factors explicitly identified
   - Reproducible analysis

5. **Risk Management**
   - Forces consideration of counterarguments
   - Identifies blind spots
   - Quantifies risk severity
   - Suggests mitigations

## Limitations & Future Work

### Current Limitations:
- Evidence limited to cached data (news, specialist input)
- No real-time data feeds (Bloomberg, FactSet)
- LLM-based analysis (subject to hallucination)
- No peer comparison framework
- Single-point-in-time analysis

### Future Enhancements:
- [ ] Real-time data integration (prices, filings, transcripts)
- [ ] Expert call transcripts analysis
- [ ] Peer company comparison
- [ ] Historical thesis tracking (how did conviction evolve?)
- [ ] Backtesting framework (thesis accuracy over time)
- [ ] Multi-agent debate on thesis (devil's advocate)
- [ ] Sentiment analysis on earnings calls
- [ ] Supply chain analysis for competitive insights

## Conclusion

The Deep Thesis Support Engine transforms thesis development from a quick-hit analysis into a **comprehensive, evidence-based investigation** that:
- Rigorously validates assumptions
- Dynamically adjusts conviction
- Identifies blind spots and risks
- Provides audit trail for decisions

**Use it whenever:**
- Committing significant capital to a position
- Thesis has >50% conviction and needs validation
- PM wants detailed rationale for positioning
- Preparing for portfolio review or debate

**Expected impact:**
- 30-50% of thesis points will have conviction increase (strong evidence found)
- 20-30% will have conviction decrease (risks/counterarguments identified)
- 20-30% will be unchanged (mixed evidence)

This systematic approach ensures every thesis is thoroughly vetted before capital allocation.
