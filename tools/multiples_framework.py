"""
Multiples Framework — Principled Approach to Fair Valuation Multiples
======================================================================

Develops a view on what reasonable P/E and EV/EBITDA multiples should be
based on:
1. Market baseline (S&P 500 forward P/E)
2. Industry characteristics
3. Company-specific factors (business model, growth, profitability, competitive position)

Usage:
    framework = MultiplesFramework()
    framework.develop_view()
    fair_multiples = framework.get_fair_multiple('NVDA')
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List


# Current market baseline (gets updated periodically)
MARKET_BASELINE = {
    'sp500_forward_pe': 22.0,          # S&P 500 forward P/E (as of Feb 2026)
    'sp500_trailing_pe': 24.5,         # S&P 500 trailing P/E
    'sp500_ev_ebitda': 16.0,           # S&P 500 EV/EBITDA
    'semiconductor_forward_pe': 28.0,  # Semiconductor sector average
    'semiconductor_ev_ebitda': 18.0,   # Semiconductor sector EV/EBITDA
    'last_updated': '2026-02-18',
}


class MultiplesFramework:
    """Framework for determining fair valuation multiples."""

    def __init__(self):
        self.data_dir = Path(__file__).parent.parent / 'data' / 'valuations'
        self.framework_file = self.data_dir / 'multiples_framework.json'
        self.market_baseline = MARKET_BASELINE.copy()
        self.company_scores = {}
        self.fair_multiples = {}

    def develop_view(self) -> Dict:
        """
        Develop comprehensive view on fair multiples for all companies.
        
        Returns framework with:
        - Market baseline
        - Company scoring (business model, growth, profitability, competitive position)
        - Fair multiple ranges
        - Reasoning
        """
        print("\n" + "="*80)
        print("  DEVELOPING MULTIPLES FRAMEWORK")
        print("="*80)

        view = {
            'timestamp': datetime.now().isoformat(),
            'market_baseline': self.market_baseline,
            'methodology': self._document_methodology(),
            'company_analysis': {},
            'fair_multiples': {},
        }

        companies = ['NVDA', 'TSM', 'ASML', 'CDNS', 'CRWV']

        for ticker in companies:
            print(f"\n  Analyzing {ticker}...")
            
            # Score the company on key factors
            scores = self._score_company(ticker)
            
            # Calculate fair multiples
            fair_pe, fair_ev = self._calculate_fair_multiples(ticker, scores)
            
            view['company_analysis'][ticker] = {
                'scores': scores,
                'reasoning': self._explain_scores(ticker, scores),
            }
            
            view['fair_multiples'][ticker] = {
                'forward_pe': {
                    'point_estimate': fair_pe,
                    'range_low': fair_pe * 0.85,
                    'range_high': fair_pe * 1.15,
                },
                'ev_ebitda': {
                    'point_estimate': fair_ev,
                    'range_low': fair_ev * 0.85,
                    'range_high': fair_ev * 1.15,
                },
            }

        # Save framework
        self._save_framework(view)
        
        print(f"\n✅ Framework developed and saved to {self.framework_file}")
        return view

    def _document_methodology(self) -> Dict:
        """Document the methodology for calculating fair multiples."""
        return {
            'baseline': 'S&P 500 forward P/E as market baseline',
            'industry_adjustment': 'Semiconductors typically trade at 1.2-1.4x market due to cyclicality and capex',
            'scoring_factors': {
                'business_model': {
                    'weight': 0.25,
                    'description': 'Asset-light, recurring revenue, margin profile',
                    'range': '0.8x - 1.3x (asset-heavy foundry vs asset-light software)',
                },
                'growth_profile': {
                    'weight': 0.30,
                    'description': 'Revenue CAGR, margin expansion trajectory',
                    'range': '0.8x - 1.5x (mature vs hyper-growth)',
                },
                'profitability': {
                    'weight': 0.25,
                    'description': 'Gross margin, ROIC, FCF conversion',
                    'range': '0.9x - 1.3x (low margins vs exceptional profitability)',
                },
                'competitive_position': {
                    'weight': 0.20,
                    'description': 'Porter\'s Five Forces, pricing power, moat strength',
                    'range': '0.8x - 1.4x (commoditized vs monopolistic)',
                },
            },
            'calculation': 'Fair P/E = Market Baseline × Industry Multiplier × Π(Factor Scores)',
            'recalibration': 'Framework should be recalibrated quarterly or when market baseline shifts >10%',
        }

    def _score_company(self, ticker: str) -> Dict:
        """
        Score company on key factors that drive multiples.
        Each factor scored 0.8 - 1.5 (below average to well above average).
        """
        scores = {
            'NVDA': {
                'business_model': 1.25,      # Asset-light design (fabless), high margin
                'growth_profile': 1.45,      # Hyper-growth in AI/datacenter
                'profitability': 1.30,       # Exceptional gross margins (>70%)
                'competitive_position': 1.40, # Near-monopoly in AI GPUs
            },
            'TSM': {
                'business_model': 0.90,      # Asset-heavy foundry (high capex)
                'growth_profile': 1.15,      # Moderate growth, levered to AI
                'profitability': 1.20,       # Strong margins for foundry (~50% GM)
                'competitive_position': 1.30, # Dominant foundry, pricing power
            },
            'ASML': {
                'business_model': 1.15,      # Equipment (lumpy but high margin)
                'growth_profile': 1.20,      # Growth tied to fab buildouts
                'profitability': 1.25,       # Very high margins (>50% GM)
                'competitive_position': 1.45, # EUV monopoly, no substitutes
            },
            'CDNS': {
                'business_model': 1.30,      # Software, recurring revenue model
                'growth_profile': 1.05,      # Mature EDA market, stable growth
                'profitability': 1.15,       # Software margins (~40% operating)
                'competitive_position': 1.10, # Duopoly with Synopsys, sticky customers
            },
            'CRWV': {
                'business_model': 0.95,      # GPU cloud rental (high capex)
                'growth_profile': 1.35,      # High growth but unprofitable
                'profitability': 0.80,       # Negative margins (investment phase)
                'competitive_position': 1.05, # Niche player, AWS/Azure/GCP competition
            },
        }
        
        return scores.get(ticker, {
            'business_model': 1.0,
            'growth_profile': 1.0,
            'profitability': 1.0,
            'competitive_position': 1.0,
        })

    def _calculate_fair_multiples(self, ticker: str, scores: Dict) -> tuple:
        """
        Calculate fair P/E and EV/EBITDA multiples.
        
        Fair P/E = S&P 500 baseline × Industry multiplier × Π(factor scores)
        """
        # Start with market baseline
        sp500_pe = self.market_baseline['sp500_forward_pe']
        
        # Industry multiplier for semiconductors/tech
        industry_multipliers = {
            'NVDA': 1.35,   # High-end semiconductors
            'TSM': 1.25,    # Foundry
            'ASML': 1.30,   # Equipment
            'CDNS': 1.20,   # EDA software
            'CRWV': 1.40,   # Cloud infrastructure (growth)
        }
        
        industry_mult = industry_multipliers.get(ticker, 1.25)
        
        # Company-specific adjustments
        company_mult = (
            scores['business_model'] ** 0.25 *
            scores['growth_profile'] ** 0.30 *
            scores['profitability'] ** 0.25 *
            scores['competitive_position'] ** 0.20
        )
        
        # Calculate fair P/E
        fair_pe = sp500_pe * industry_mult * company_mult
        
        # EV/EBITDA typically ~75-80% of P/E multiple for tech companies
        fair_ev = fair_pe * 0.75
        
        return round(fair_pe, 1), round(fair_ev, 1)

    def _explain_scores(self, ticker: str, scores: Dict) -> str:
        """Generate reasoning for the scores assigned."""
        explanations = {
            'NVDA': (
                "NVIDIA commands premium multiples due to: (1) Asset-light fabless model with "
                "70%+ gross margins, (2) Hyper-growth in AI/datacenter driving 40%+ revenue growth, "
                "(3) Exceptional profitability with industry-leading ROIC, (4) Near-monopoly in AI GPUs "
                "with CUDA moat creating extreme pricing power. Justifies 1.3-1.5x sector premium."
            ),
            'TSM': (
                "TSMC trades at moderate premium to semiconductors due to: (1) Asset-heavy foundry model "
                "with high capex requirements, (2) Steady growth levered to AI and advanced nodes, "
                "(3) Strong 50% gross margins for foundry business, (4) Dominant position in leading-edge "
                "manufacturing with limited competition. Pricing power from technology leadership."
            ),
            'ASML': (
                "ASML deserves premium multiples due to: (1) Equipment model with lumpy revenue but high "
                "margins, (2) Growth tied to global fab buildouts, (3) Exceptional 50%+ gross margins, "
                "(4) EUV lithography monopoly with no viable substitutes - ultimate moat. Customers have "
                "no choice but to pay premium pricing."
            ),
            'CDNS': (
                "Cadence trades at software-like multiples due to: (1) SaaS/subscription revenue model with "
                "recurring streams, (2) Mature EDA market with stable mid-single-digit growth, (3) Software "
                "margins (~40% operating), (4) Duopoly with Synopsys creating pricing power and sticky "
                "customer relationships. Lower growth limits premium expansion."
            ),
            'CRWV': (
                "CoreWeave multiples are volatile due to: (1) GPU cloud rental with high capex creating "
                "asset-heavy model, (2) Hyper-growth in AI inference market, (3) Currently unprofitable "
                "(negative margins) limiting multiple, (4) Faces intense competition from hyperscalers "
                "(AWS, Azure, GCP) with deeper pockets. Growth story vs profitability challenge."
            ),
        }
        
        return explanations.get(ticker, "No detailed analysis available")

    def _save_framework(self, view: Dict):
        """Save framework to JSON file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.framework_file, 'w') as f:
            json.dump(view, f, indent=2)

    def load_framework(self) -> Dict:
        """Load existing framework from file."""
        if self.framework_file.exists():
            with open(self.framework_file, 'r') as f:
                return json.load(f)
        return {}

    def get_fair_multiple(self, ticker: str, multiple_type: str = 'forward_pe') -> Dict:
        """Get fair multiple for a specific ticker."""
        framework = self.load_framework()
        if ticker in framework.get('fair_multiples', {}):
            return framework['fair_multiples'][ticker].get(multiple_type, {})
        return {}

    def compare_to_market(self, ticker: str, actual_pe: float, actual_ev: float = None) -> Dict:
        """
        Compare actual market multiples to fair multiples.
        Returns assessment of over/undervaluation.
        """
        framework = self.load_framework()
        if ticker not in framework.get('fair_multiples', {}):
            return {'error': 'No framework for ticker'}

        fair = framework['fair_multiples'][ticker]
        fair_pe = fair['forward_pe']['point_estimate']
        fair_pe_low = fair['forward_pe']['range_low']
        fair_pe_high = fair['forward_pe']['range_high']

        # Assess P/E valuation
        if actual_pe < fair_pe_low:
            pe_assessment = f"UNDERVALUED: Trading at {actual_pe:.1f}x vs fair range {fair_pe_low:.1f}x-{fair_pe_high:.1f}x"
        elif actual_pe > fair_pe_high:
            pe_assessment = f"OVERVALUED: Trading at {actual_pe:.1f}x vs fair range {fair_pe_low:.1f}x-{fair_pe_high:.1f}x"
        else:
            pe_assessment = f"FAIRLY VALUED: Trading at {actual_pe:.1f}x within fair range {fair_pe_low:.1f}x-{fair_pe_high:.1f}x"

        result = {
            'ticker': ticker,
            'actual_pe': actual_pe,
            'fair_pe': fair_pe,
            'fair_range': f"{fair_pe_low:.1f}x - {fair_pe_high:.1f}x",
            'premium_discount': (actual_pe / fair_pe - 1) if fair_pe > 0 else 0,
            'assessment': pe_assessment,
        }

        # EV/EBITDA if provided
        if actual_ev:
            fair_ev = fair['ev_ebitda']['point_estimate']
            result['actual_ev_ebitda'] = actual_ev
            result['fair_ev_ebitda'] = fair_ev

        return result


if __name__ == '__main__':
    framework = MultiplesFramework()
    view = framework.develop_view()

    print("\n" + "="*80)
    print("  FAIR MULTIPLES SUMMARY")
    print("="*80)

    print(f"\nMarket Baseline: S&P 500 Forward P/E = {view['market_baseline']['sp500_forward_pe']:.1f}x")
    print(f"Semiconductor Sector Avg: {view['market_baseline']['semiconductor_forward_pe']:.1f}x\n")

    for ticker in ['NVDA', 'TSM', 'ASML', 'CDNS', 'CRWV']:
        fair = view['fair_multiples'][ticker]
        scores = view['company_analysis'][ticker]['scores']
        
        print(f"\n{ticker}:")
        print(f"  Fair P/E:      {fair['forward_pe']['point_estimate']:.1f}x "
              f"(range: {fair['forward_pe']['range_low']:.1f}x - {fair['forward_pe']['range_high']:.1f}x)")
        print(f"  Fair EV/EBITDA: {fair['ev_ebitda']['point_estimate']:.1f}x "
              f"(range: {fair['ev_ebitda']['range_low']:.1f}x - {fair['ev_ebitda']['range_high']:.1f}x)")
        print(f"  Scores: BizModel={scores['business_model']:.2f}, "
              f"Growth={scores['growth_profile']:.2f}, "
              f"Profit={scores['profitability']:.2f}, "
              f"Competitive={scores['competitive_position']:.2f}")

    # Test comparison
    print("\n" + "="*80)
    print("  MARKET COMPARISON (Example: NVDA at 28x P/E)")
    print("="*80)
    
    comparison = framework.compare_to_market('NVDA', actual_pe=28.0)
    print(f"\n{comparison['assessment']}")
    print(f"Premium/Discount: {comparison['premium_discount']:+.1%}")

