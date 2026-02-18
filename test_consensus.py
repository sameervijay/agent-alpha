"""
Test Consensus Understanding for Company Analysts
==================================================
Demonstrates how analysts can:
1. Read consensus estimates from Excel
2. Compare to their own model assumptions
3. Identify material differences
4. Use this as input to thesis development
"""

import sys
sys.path.insert(0, '.')

from agents.company_analyst_agent import CompanyAnalystAgent


def test_consensus_understanding(ticker='NVDA'):
    """Test consensus understanding for a specific ticker."""

    print(f"\n{'='*80}")
    print(f"  CONSENSUS UNDERSTANDING TEST: {ticker}")
    print(f"{'='*80}\n")

    # Create analyst
    analyst = CompanyAnalystAgent(ticker)

    # Get consensus comparison
    result = analyst.understand_consensus()

    # Print summary
    print(f"\n{'='*80}")
    print("  SUMMARY")
    print(f"{'='*80}")
    print(result['summary'])

    # Print detailed differences for one year
    if result.get('differences'):
        print(f"\n{'='*80}")
        print("  DETAILED DIFFERENCES - FY2027")
        print(f"{'='*80}")

        fy27 = result['differences'].get('FY2027', {})

        if 'revenue' in fy27:
            d = fy27['revenue']
            print(f"\nRevenue:")
            print(f"  Consensus:    ${d['consensus']:>12,.0f}M")
            print(f"  Own Model:    ${d['own']:>12,.0f}M")
            print(f"  Difference:   {d['direction']:>8} by {d['diff_pct']:>6.1%}")
            print(f"  Material:     {'YES' if d['material'] else 'no'}")

        if 'operating_income' in fy27:
            d = fy27['operating_income']
            print(f"\nOperating Income:")
            print(f"  Consensus:    ${d['consensus']:>12,.0f}M")
            print(f"  Own Model:    ${d['own']:>12,.0f}M")
            print(f"  Difference:   {d['direction']:>8} by {d['diff_pct']:>6.1%}")
            print(f"  Material:     {'YES' if d['material'] else 'no'}")

        if 'operating_margin' in fy27:
            d = fy27['operating_margin']
            print(f"\nOperating Margin:")
            print(f"  Consensus:    {d['consensus']:>12.1%}")
            print(f"  Own Model:    {d['own']:>12.1%}")
            print(f"  Difference:   {d['direction']:>8} by {d['diff_bps']:>6.0f}bps")
            print(f"  Material:     {'YES' if d['material'] else 'no'}")

        # Segment differences
        if 'segments' in fy27:
            print(f"\nSegment Differences:")
            for seg, seg_data in fy27['segments'].items():
                if seg_data.get('material'):
                    print(f"  {seg.upper()}: {seg_data['direction']} by {seg_data['diff_pct']:.1%}")

    return result


def demonstrate_thesis_integration():
    """Demonstrate how consensus feeds into thesis development."""

    print(f"\n{'='*80}")
    print("  THESIS DEVELOPMENT WITH CONSENSUS")
    print(f"{'='*80}\n")

    analyst = CompanyAnalystAgent('NVDA')

    print("When develop_thesis() is called, it will:")
    print("  1. Call understand_consensus() to compare model vs consensus")
    print("  2. Include consensus differences in LLM context")
    print("  3. Generate thesis points that explain the differences")
    print("  4. Conduct supporting analyses")
    print("  5. Quantify into DCF driver changes")

    print("\nExample consensus context that would be passed to LLM:")
    result = analyst.understand_consensus()
    print("\n" + "-"*80)
    print(result['summary'])
    print("-"*80)

    print("\nThe LLM would then generate thesis points like:")
    print("  - 'NVDA margins will be lower due to increased R&D for next-gen'")
    print("  - 'Datacenter growth will slow due to market saturation'")
    print("  - etc.")


if __name__ == '__main__':
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'NVDA'

    # Test 1: Consensus understanding
    result = test_consensus_understanding(ticker)

    # Test 2: Show thesis integration
    print("\n" * 2)
    demonstrate_thesis_integration()

    print("\n" + "="*80)
    print("  TEST COMPLETE")
    print("="*80)
    print("\nConsensus understanding is now integrated into thesis development.")
    print("The analyst can identify where its model differs from consensus")
    print("and develop thesis points to explain those differences.\n")
