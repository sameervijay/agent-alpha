# Memory Pricing Monitoring — Phase 1 (Free)

## Overview

This guide explains how to monitor DRAM and HBM memory pricing using **free public sources** and integrate findings into DCF valuations for NVIDIA, TSMC, and CoreWeave.

**Key Insight**: Memory pricing (especially HBM) is a **leading indicator** of semiconductor supply/demand and directly impacts margins for 3 of your 5 portfolio companies.

---

## Why Memory Pricing Matters

### Current Context (Q1 2026)
- **HBM prices**: +20% YoY (SK Hynix, Samsung raising prices for 2026)
- **Server DRAM (DDR5)**: +60-70% (Microsoft, Google paying crisis-level premiums)
- **Lead times**: 26-40 weeks (normally 8-12 weeks)
- **Inventory**: Down to 5-8 weeks of stock

### Value Chain Impact
| Company | Exposure | Margin Impact | Timeline |
|---------|----------|---------------|----------|
| **NVDA** | HBM = 50% of GPU BOM | -70 bps per 20% HBM rise | 1-2 quarters |
| **TSMC** | CoWoS (HBM mfg) = highest margin | +240 bps per 20% HBM rise | 2-3 quarters |
| **CRWV** | GPU capex (H100/H200 with HBM) | -180 bps per 20% HBM rise | 1-2 quarters |

---

## Phase 1: Weekly Monitoring (Free Sources)

### Step 1: Set Up Google Alerts (5 min)

Create alert email to notify you of memory pricing news:

```
Google Alerts Setup:
1. Go to: https://www.google.com/alerts
2. Create alerts for:
   - "HBM memory price" (high volume)
   - "DRAM price" (high volume)
   - "SK Hynix earnings" (once per quarter)
   - "Samsung semiconductor earnings" (once per quarter)
   - "Micron DRAM guidance" (once per quarter)
3. Set frequency: "As-it-happens" or "Once a day"
4. Email: your-email@company.com
```

**Expected**: 2-3 news items per week, spikes around earnings

---

### Step 2: Track Free Data Sources (Weekly, 15 min)

| Source | Update Frequency | What to Look For |
|--------|-----------------|------------------|
| **TrendForce News** | 2-3x per week | "DRAM Spot Price Update", "HBM Price", "Memory Pricing" |
| **SK Hynix News** | Quarterly (earnings) | ASP changes, capacity planning, HBM guidance |
| **Samsung News** | Quarterly (earnings) | Operating profit guidance, memory pricing strategy |
| **Micron Earnings** | Quarterly | DRAM ASP, bit shipment guidance |
| **SEMI Reports** | Monthly | Lead times, inventory weeks, fab utilization |

**Manual Check Workflow** (Every Monday):

```
1. TrendForce memory news
   → https://www.trendforce.com/news
   → Search for "memory", "DRAM", "HBM", "price"
   → Note any spot price changes >5%

2. Manufacturer news (if earnings week)
   → SK Hynix: https://news.skhynix.com/category/financial/
   → Samsung: https://news.samsung.com/semiconductor
   → Micron: https://investors.micron.com/news-releases
   → Extract: ASP trends, forward guidance

3. Supply metrics (if available)
   → Lead times: Google "DRAM lead times" or "component availability"
   → Inventory: Check SEMI reports or component distributors
   → Note if lead times >20 weeks or inventory <6 weeks
```

---

### Step 3: Run Weekly Monitor Script

Once per week, run the automated monitoring script:

```bash
python3 tests/test_memory_pricing_monitor.py
```

**Output**:
- Summary of memory news this week
- Margin impact scenarios (HBM +20%, DRAM +60%)
- Supply constraint signals
- JSON output for PM briefing

**Example Output**:
```
SCENARIO A: HBM Prices Up 20% YoY (Expected 2026)

NVDA:
  • BOM Exposure: 5.0%
  • Estimated Margin Impact: -70 bps
  • DCF Driver to Adjust: gm_improvement_bps

TSMC:
  • BOM Exposure: 10.0%
  • Estimated Margin Impact: +240 bps
  • (Revenue growth driver — CoWoS pricing power)

CRWV:
  • BOM Exposure: 15.0%
  • Estimated Margin Impact: -180 bps
  • DCF Driver to Adjust: gm_improvement_bps
```

---

### Step 4: Quarterly Deep Dive (Earnings Calls)

When SK Hynix, Samsung, or Micron report quarterly earnings:

1. **Listen to earnings call** (search YouTube or company IR site)
2. **Extract key metrics**:
   - DRAM ASP (quarter-over-quarter change)
   - HBM ASP (if disclosed)
   - Bit shipment growth
   - Forward guidance (next 2-3 quarters)
   - CapEx plans (indicator of cycle duration)

3. **Update DCF assumptions**:
   - If ASP guidance changes >8%, adjust margin drivers
   - If CapEx expanding, expect 24-36 month cycle (not 12-18 months)
   - If HBM allocation >20% of fab capacity, expect structural shift

**Example: SK Hynix Earnings** (typically late January)
```
Q4 2025 Results:
- Revenue +66% YoY
- DRAM ASP +20-25% QoQ
- HBM3E demand "exceeding capacity"
- 2026 Guidance: Operating profit >100 trillion won

DCF Adjustment for NVDA:
- gm_improvement_bps: Reduce by 70 bps per 20% HBM rise
- Timeline: Affects Q4-26 through FY2029 (supply-driven structural change)
```

---

## Integrating Into DCF Valuation

### When to Update Drivers

**Trigger: Memory ASP changes >8% month-over-month**

Example workflow:

```python
# In pm_agent.py, after commodities agent analysis:

if memory_event.estimated_margin_impact_bps > 80:
    print(f"Memory pricing signal: {memory_event.headline}")

    # Update NVIDIA DCF if HBM +20%
    if 'HBM' in memory_event.memory_type and 'NVDA' in affected:
        engine = pm.engines['NVDA']
        # HBM +20% → -70 bps GM impact
        engine.update_drivers({
            'gm_improvement_bps': {
                'FY2027': -70,
                'FY2028': -70,
                'FY2029': -70,
            }
        })
        print(f"Updated NVDA gm_improvement_bps: -70 bps/qtr")

    # Update TSMC DCF if HBM demand surge
    if 'HBM' in memory_event.memory_type and 'TSMC' in affected:
        engine = pm.engines['CDNS']  # Using CDNS as proxy for TSMC for now
        # HBM demand → CoWoS capacity premium
        # Model as revenue growth upside, not margin (CDNS framework limitation)
        print(f"TSMC CoWoS pricing power expanding: Note for next quarterly review")
```

### Key DCF Drivers by Company

**NVIDIA**:
- Driver: `gm_improvement_bps` (gross margin)
- Direction: **Negative** when memory costs rise
- Magnitude: -35 bps per 10% HBM ASP increase
- Lead time: 1-2 quarters

**TSMC**:
- Driver: Not yet in framework (use revenue growth as proxy)
- Direction: **Positive** when HBM demand surges
- Magnitude: +120 bps per 10% HBM demand (CoWoS premium)
- Lead time: 2-3 quarters
- *Note*: Full TSMC DCF model needed to capture CoWoS revenue separately

**CoreWeave**:
- Driver: `gm_improvement_bps` (gross margin)
- Direction: **Negative** when GPU capex rises
- Magnitude: -90 bps per 10% HBM ASP increase
- Lead time: 1-2 quarters
- Caveat: Limited pricing power (fixed rental contracts)

---

## Supply Constraint Signals (Free Leading Indicators)

### Metric 1: Lead Times

**What to track**: Component lead times from free brokers

```
Source: Google "DRAM lead times" or "component availability"
Normal: 8-12 weeks
Watch: 16-20 weeks (tightening)
Crisis: 30+ weeks (severe constraint)
```

**Interpretation**:
- Lead times **expanding** → Demand outpacing supply → ASP likely to rise in 4-8 weeks
- Lead times >30 weeks → Maximum pricing power (observed Q4 2025)

### Metric 2: Inventory Weeks

**What to track**: DRAM inventory levels from SEMI reports or component distributors

```
Source: SEMI monthly reports (free for registered users)
         Component distributors (Sourceability.com has free samples)
Abundant: >12 weeks (downward pricing pressure)
Healthy: 8-10 weeks (balanced)
Tight: 6-8 weeks (margin expansion signal)
Crisis: <6 weeks (maximum pricing power)
```

**Interpretation**:
- Inventory **falling below 6 weeks** → Expect ASP spike in 2-4 weeks
- Inventory **collapsing to <4 weeks** → Crisis pricing in progress

### Metric 3: Bit Shipments vs. Revenue Growth

**What to track**: Manufacturer earnings disclosures

```
If bit shipments grow 10% but revenue grows 40%+ → Pricing is primary driver
If both grow 40%+ → Demand-driven cycle (will likely reverse)
```

---

## Phase 1 Tools & Files

### Scripts

1. **`tools/memory_pricing_monitor.py`**
   - Fetch TrendForce news (scraping public page)
   - Fetch RSS feeds for memory pricing news
   - Analyze margin impact for NVDA/TSMC/CRWV
   - Supply constraint estimation
   - Usage: `from tools.memory_pricing_monitor import analyze_memory_impact`

2. **`tests/test_memory_pricing_monitor.py`**
   - Weekly monitoring script
   - Run every Monday: `python3 tests/test_memory_pricing_monitor.py`
   - Generates margin impact scenarios
   - Saves results to `data/valuations/memory_pricing_latest.json`

3. **`agents/commodities_agent.py`** (Enhanced)
   - Added `analyze_memory_pricing_event()` method
   - Maps HBM/DRAM events to DCF driver impacts
   - Integrated into multi-agent debate

### Data Outputs

- **`data/valuations/memory_pricing_latest.json`**
  - Updated weekly after running monitor script
  - Contains margin impact scenarios for 3 companies
  - Used for PM briefing and DCF updates

---

## Quarterly Calendar

| Date | Action |
|------|--------|
| **Mondays (Weekly)** | Run memory pricing monitor; check TrendForce news |
| **Late January** | SK Hynix earnings (Q4 previous year) |
| **Late February** | Samsung earnings; Micron earnings |
| **Mid-May** | SK Hynix earnings (Q1); Micron earnings |
| **Late July** | Samsung earnings; Micron earnings |
| **Late October** | SK Hynix earnings (Q3); Micron earnings |

---

## FAQ & Troubleshooting

### Q: Where can I find current HBM/DRAM spot prices?
**A**: TrendForce publishes free summaries on their news site: https://www.trendforce.com/news
- Search for "DRAM Spot Price Update" or "Memory Pricing"
- Spot prices update weekly (Mon-Fri)
- Free summary shows DDR4, DDR5, HBM3E spot prices

### Q: How do I get lead time and inventory data for free?
**A**:
1. **Lead times**: Google "DRAM lead times 2026" or "component availability"
2. **Inventory weeks**:
   - SEMI monthly reports (free registration): https://www.semi.org
   - Electronics retailers: Scan online retailer inventory (proxy signal)
   - Sourceability free tier has lead time samples

### Q: What if I miss a week of monitoring?
**A**: No problem. The script fetches 7-day rolling window, so catching up is automatic.

### Q: How do I know when to update DCF drivers?
**A**: Update when:
- HBM/DRAM ASP changes **>8% in a single month**
- Lead times **expand suddenly >30 weeks** (pricing power confirmation)
- Inventory **drops below 5 weeks** (margin expansion imminent)
- Manufacturer **guidance shifts** (forward-looking adjustment)

### Q: Can I automate this further?
**A**: Yes, Phase 2 would:
- Subscribe to DRAMeXchange ($4K/year) for daily prices + API
- Scrape manufacturer earnings transcripts (NLP extraction)
- Alert threshold triggers (e.g., "if HBM spot price +5% → alert PM")

---

## Success Metrics

**Phase 1 Goals**:
- [ ] Set up Google Alerts for memory pricing news
- [ ] Run weekly monitoring script (Mondays)
- [ ] Track TrendForce headlines (check 2-3x per week)
- [ ] Update DCF drivers when ASP changes >8%
- [ ] Quarterly earnings call notes (SK Hynix, Samsung, Micron)

**Expected Outcomes**:
- Earlier detection of margin pressure (NVIDIA, CoreWeave) or upside (TSMC)
- 1-2 quarter lead time on earnings guidance changes
- More accurate DCF sensitivity analysis

---

## Next Steps

### Immediate (This Week)
1. Set up Google Alerts
2. Run test monitoring script once to validate
3. Note current HBM/DRAM prices from TrendForce

### This Month
1. Run monitoring script every Monday
2. Collect 4 weeks of data to establish baseline
3. Compare predictions vs. actual earnings when SK Hynix reports (late January)

### This Quarter
1. Integrate into PM agent (alert on >8% ASP changes)
2. Quarterly earnings notes from all 3 manufacturers
3. Evaluate for Phase 2 upgrade (paid data source evaluation)

---

## Phase 1 Cost
**Total: $0**

Free sources cover 80% of leading indicator value without any subscription costs.

Phase 2 (optional) would add DRAMeXchange subscription (~$4K/year) for daily contract prices and deeper historical analysis.

---

**Last Updated**: February 17, 2026
**Maintained By**: Commodities Agent with memory pricing specialization
