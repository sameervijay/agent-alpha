"""
Thesis Point Support Engine
============================
Deep analysis framework for validating and strengthening investment thesis points.

Conducts multi-faceted analysis including:
- Evidence gathering from multiple sources
- Quantitative data analysis
- Risk assessment and counterarguments
- Conviction scoring based on evidence strength
- DCF driver quantification

Usage:
    from agents.thesis_support import ThesisSupport

    support = ThesisSupport(ticker='NVDA', analyst_agent=analyst)
    result = support.support_thesis_point(thesis_point)
"""

from typing import Dict, List, Optional
from datetime import datetime
import json


class ThesisSupport:
    """Deep analysis engine for supporting thesis points."""

    def __init__(self, ticker: str, analyst_agent):
        self.ticker = ticker
        self.analyst = analyst_agent

    def support_thesis_point(self, thesis_point: dict, depth: str = 'deep') -> dict:
        """
        Conduct comprehensive analysis to support or refute a thesis point.

        Args:
            thesis_point: Dict with thesis, direction, key_questions, etc.
            depth: 'quick' (3 analyses), 'deep' (5 analyses), 'exhaustive' (7+ analyses)

        Returns:
            {
                'thesis_point': original thesis point,
                'analyses': [...],
                'quantitative_evidence': {...},
                'risks_counterarguments': [...],
                'conviction_assessment': {
                    'initial_conviction': float,
                    'evidence_strength': float,
                    'final_conviction': float,
                    'rationale': str,
                },
                'dcf_implications': {...},
                'summary': str,
            }
        """
        print(f"\n{'='*80}")
        print(f"  DEEP THESIS SUPPORT: {thesis_point.get('thesis', '')[:60]}...")
        print(f"{'='*80}")
        print(f"  Depth: {depth.upper()}")
        print(f"  Direction: {thesis_point.get('direction', 'unknown').upper()}")
        print(f"  Initial Conviction: {thesis_point.get('conviction', 0):.0%}\n")

        # Step 1: Expand key questions
        expanded_questions = self._expand_key_questions(thesis_point, depth)

        # Step 2: Conduct analyses for each question
        analyses = []
        for i, question in enumerate(expanded_questions, 1):
            print(f"  Analysis {i}/{len(expanded_questions)}: {question[:70]}...")
            analysis = self._conduct_deep_analysis(question, thesis_point)
            analyses.append(analysis)

        # Step 3: Gather quantitative evidence
        print(f"\n  Gathering quantitative evidence...")
        quant_evidence = self._gather_quantitative_evidence(thesis_point, analyses)

        # Step 4: Identify risks and counterarguments
        print(f"  Identifying risks and counterarguments...")
        risks = self._identify_risks_counterarguments(thesis_point, analyses)

        # Step 5: Assess conviction based on evidence
        print(f"  Assessing conviction based on evidence strength...")
        conviction_assessment = self._assess_conviction(thesis_point, analyses, quant_evidence, risks)

        # Step 6: Quantify DCF implications
        print(f"  Quantifying DCF driver implications...")
        dcf_implications = self._quantify_dcf_implications(thesis_point, analyses, conviction_assessment)

        # Step 7: Generate summary
        summary = self._generate_support_summary(thesis_point, analyses, conviction_assessment, dcf_implications)

        result = {
            'timestamp': datetime.now().isoformat(),
            'thesis_point': thesis_point,
            'analyses': analyses,
            'quantitative_evidence': quant_evidence,
            'risks_counterarguments': risks,
            'conviction_assessment': conviction_assessment,
            'dcf_implications': dcf_implications,
            'summary': summary,
        }

        print(f"\n  ✅ Thesis support complete")
        return result

    def _expand_key_questions(self, thesis_point: dict, depth: str) -> List[str]:
        """Expand key questions based on depth level."""
        base_questions = thesis_point.get('key_questions', [])

        num_questions = {
            'quick': 3,
            'deep': 5,
            'exhaustive': 7,
        }.get(depth, 5)

        if len(base_questions) >= num_questions:
            return base_questions[:num_questions]

        # Use LLM to generate additional questions
        prompt = f"""Given this investment thesis:

Thesis: {thesis_point.get('thesis')}
Direction: {thesis_point.get('direction')}
Existing questions: {base_questions}

Generate {num_questions - len(base_questions)} additional analytical questions that would help validate or refute this thesis.

Focus on:
1. Quantitative metrics (growth rates, market sizes, pricing trends)
2. Competitive dynamics (market share, new entrants, substitutes)
3. Customer behavior (demand drivers, adoption curves, willingness to pay)
4. Financial impact (revenue/margin drivers, cost structure)
5. Risk factors (what could go wrong, alternative scenarios)

Return JSON:
{{
  "additional_questions": ["Question 1", "Question 2", ...]
}}"""

        try:
            data = self.analyst.call_llm_json(prompt)
            additional = data.get('additional_questions', [])
            return base_questions + additional[:num_questions - len(base_questions)]
        except:
            return base_questions

    def _conduct_deep_analysis(self, question: str, thesis_point: dict) -> dict:
        """Conduct a single deep analysis."""
        # This is more thorough than the standard _gather_evidence_for_question

        # Gather evidence from multiple sources
        evidence_sources = {
            'company_news': None,
            'specialist_input': None,
            'consensus_data': None,
            'market_data': None,
        }

        # Company news
        try:
            from tools.news_fetcher import fetch_all_news
            news_items = fetch_all_news(self.ticker, max_items=10)
            evidence_sources['company_news'] = [
                {'headline': item.headline, 'summary': item.summary}
                for item in news_items[:5]
            ]
        except:
            pass

        # Specialist input
        try:
            specialist = self.analyst.seek_specialist_input()
            evidence_sources['specialist_input'] = specialist.get('narrative', '')
        except:
            pass

        # Consensus data
        try:
            consensus = self.analyst.understand_consensus()
            evidence_sources['consensus_data'] = consensus.get('summary', '')
        except:
            pass

        # Market data (valuation context)
        try:
            valuation = self.analyst.check_market_valuation()
            evidence_sources['market_data'] = valuation.get('assessment', '')
        except:
            pass

        # Synthesize evidence with LLM
        prompt = f"""Analyze the following question in the context of this investment thesis:

Thesis: {thesis_point.get('thesis')}
Direction: {thesis_point.get('direction')}
Question: {question}

Evidence available:

Company News:
{json.dumps(evidence_sources.get('company_news', []), indent=2)}

Specialist Analysis:
{evidence_sources.get('specialist_input', 'N/A')}

Consensus Comparison:
{evidence_sources.get('consensus_data', 'N/A')}

Market Valuation:
{evidence_sources.get('market_data', 'N/A')}

Provide a comprehensive analysis:

Return JSON:
{{
  "analysis_type": "competitive|demand|margin|risk",
  "finding": "Clear statement of what the evidence shows",
  "evidence_summary": "Summary of key evidence supporting the finding",
  "confidence": 0.0-1.0,
  "rationale": "Detailed explanation of reasoning",
  "data_points": ["Specific quantitative fact 1", "Specific quantitative fact 2"],
  "supports_thesis": true/false,
  "strength": "strong|moderate|weak"
}}"""

        try:
            data = self.analyst.call_llm_json(prompt)
            data['question'] = question
            data['evidence_sources'] = evidence_sources
            return data
        except Exception as e:
            return {
                'question': question,
                'analysis_type': 'unknown',
                'finding': f'Analysis failed: {e}',
                'confidence': 0.0,
                'supports_thesis': None,
                'strength': 'weak',
            }

    def _gather_quantitative_evidence(self, thesis_point: dict, analyses: List[dict]) -> dict:
        """Extract and structure quantitative evidence from analyses."""
        quant_evidence = {
            'data_points': [],
            'growth_rates': [],
            'market_sizes': [],
            'margin_impacts': [],
            'competitive_metrics': [],
        }

        # Extract data points from analyses
        for analysis in analyses:
            data_points = analysis.get('data_points', [])
            quant_evidence['data_points'].extend(data_points)

            # Parse for specific types
            for dp in data_points:
                dp_lower = dp.lower()
                if 'growth' in dp_lower or 'cagr' in dp_lower or 'yoy' in dp_lower:
                    quant_evidence['growth_rates'].append(dp)
                elif 'market' in dp_lower or 'tam' in dp_lower or 'addressable' in dp_lower:
                    quant_evidence['market_sizes'].append(dp)
                elif 'margin' in dp_lower or 'bps' in dp_lower:
                    quant_evidence['margin_impacts'].append(dp)
                elif 'share' in dp_lower or 'competitor' in dp_lower:
                    quant_evidence['competitive_metrics'].append(dp)

        return quant_evidence

    def _identify_risks_counterarguments(self, thesis_point: dict, analyses: List[dict]) -> List[dict]:
        """Identify key risks and counterarguments to the thesis."""

        # Check which analyses refute the thesis
        refuting_analyses = [a for a in analyses if not a.get('supports_thesis', True)]

        prompt = f"""Given this investment thesis and supporting analyses, identify the key risks and counterarguments:

Thesis: {thesis_point.get('thesis')}
Direction: {thesis_point.get('direction')}

Analyses conducted: {len(analyses)}
- Supporting: {len([a for a in analyses if a.get('supports_thesis', True)])}
- Refuting: {len(refuting_analyses)}

Evidence that contradicts thesis:
{json.dumps([a.get('finding') for a in refuting_analyses], indent=2)}

Identify 3-5 key risks or counterarguments:

Return JSON:
{{
  "risks": [
    {{
      "risk": "Description of risk/counterargument",
      "severity": "high|medium|low",
      "probability": 0.0-1.0,
      "mitigation": "How this risk could be mitigated or is less severe than it appears"
    }},
    ...
  ]
}}"""

        try:
            data = self.analyst.call_llm_json(prompt)
            return data.get('risks', [])
        except:
            return []

    def _assess_conviction(self, thesis_point: dict, analyses: List[dict],
                          quant_evidence: dict, risks: List[dict]) -> dict:
        """Assess conviction based on evidence strength."""

        initial_conviction = thesis_point.get('conviction', 0.5)

        # Count supporting vs refuting analyses
        supporting = [a for a in analyses if a.get('supports_thesis', True)]
        refuting = [a for a in analyses if not a.get('supports_thesis', True)]

        # Weight by confidence
        support_score = sum(a.get('confidence', 0) for a in supporting) / len(analyses) if analyses else 0
        refute_score = sum(a.get('confidence', 0) for a in refuting) / len(analyses) if analyses else 0

        # Assess strength of quantitative evidence
        quant_strength = min(1.0, len(quant_evidence.get('data_points', [])) / 10)

        # Assess risk severity
        high_severity_risks = [r for r in risks if r.get('severity') == 'high']
        risk_penalty = len(high_severity_risks) * 0.1

        # Calculate final conviction
        evidence_strength = (support_score - refute_score + quant_strength) / 2
        final_conviction = max(0.1, min(0.95, initial_conviction + evidence_strength - risk_penalty))

        return {
            'initial_conviction': initial_conviction,
            'supporting_analyses': len(supporting),
            'refuting_analyses': len(refuting),
            'support_score': support_score,
            'refute_score': refute_score,
            'quantitative_strength': quant_strength,
            'risk_penalty': risk_penalty,
            'evidence_strength': evidence_strength,
            'final_conviction': final_conviction,
            'change': final_conviction - initial_conviction,
            'rationale': self._conviction_rationale(
                initial_conviction, final_conviction, len(supporting),
                len(refuting), quant_strength, len(high_severity_risks)
            ),
        }

    def _conviction_rationale(self, initial: float, final: float, n_support: int,
                             n_refute: int, quant: float, n_high_risks: int) -> str:
        """Generate rationale for conviction change."""
        change = final - initial
        direction = "increased" if change > 0 else "decreased" if change < 0 else "maintained"

        return (
            f"Conviction {direction} from {initial:.0%} to {final:.0%} "
            f"({change:+.0%}) based on: {n_support} supporting analyses, "
            f"{n_refute} refuting analyses, "
            f"quantitative evidence strength {quant:.0%}, "
            f"and {n_high_risks} high-severity risks identified."
        )

    def _quantify_dcf_implications(self, thesis_point: dict, analyses: List[dict],
                                   conviction: dict) -> dict:
        """Quantify thesis into DCF driver changes."""

        # Use the analyst's existing method but enhance with conviction
        base_implications = self.analyst._quantify_thesis_to_drivers(thesis_point)

        # Adjust driver changes based on conviction
        final_conviction = conviction['final_conviction']
        driver_changes = base_implications.get('driver_changes', {})

        # Scale driver changes by conviction level
        # Higher conviction = more aggressive changes
        conviction_multiplier = final_conviction / thesis_point.get('conviction', 0.5)

        adjusted_changes = {}
        for driver, changes in driver_changes.items():
            adjusted_changes[driver] = {}
            for period, value in changes.items():
                if period not in ['baseline', 'change', 'rationale']:
                    # Scale the change by conviction multiplier
                    if isinstance(value, (int, float)):
                        baseline = changes.get('baseline', value)
                        delta = value - baseline
                        adjusted_value = baseline + (delta * conviction_multiplier)
                        adjusted_changes[driver][period] = round(adjusted_value, 4)
                    else:
                        adjusted_changes[driver][period] = value

            # Copy over baseline, change, rationale
            if 'baseline' in changes:
                adjusted_changes[driver]['baseline'] = changes['baseline']
            if 'rationale' in changes:
                adjusted_changes[driver]['rationale'] = changes['rationale']

        return {
            'driver_changes': adjusted_changes,
            'conviction': final_conviction,
            'sensitivity': base_implications.get('sensitivity', 'Medium'),
            'adjustment_note': f"Driver changes scaled by conviction multiplier: {conviction_multiplier:.2f}x",
        }

    def _generate_support_summary(self, thesis_point: dict, analyses: List[dict],
                                 conviction: dict, dcf_implications: dict) -> str:
        """Generate a comprehensive summary of thesis support."""
        lines = [
            f"Thesis Support Summary",
            f"=" * 60,
            f"",
            f"Thesis: {thesis_point.get('thesis')}",
            f"Direction: {thesis_point.get('direction', 'unknown').upper()}",
            f"",
            f"Conviction:",
            f"  Initial: {conviction['initial_conviction']:.0%}",
            f"  Final:   {conviction['final_conviction']:.0%}",
            f"  Change:  {conviction['change']:+.0%}",
            f"",
            f"Evidence Analysis:",
            f"  Total analyses: {len(analyses)}",
            f"  Supporting: {conviction['supporting_analyses']}",
            f"  Refuting: {conviction['refuting_analyses']}",
            f"  Quantitative data points: {len(conviction)}",
            f"",
            f"DCF Implications:",
        ]

        for driver, changes in dcf_implications.get('driver_changes', {}).items():
            lines.append(f"  {driver}:")
            for period, value in changes.items():
                if period not in ['baseline', 'change', 'rationale']:
                    lines.append(f"    {period}: {value}")

        lines.append(f"")
        lines.append(conviction['rationale'])

        return "\n".join(lines)


# Convenience function for quick access
def support_thesis_point(ticker: str, thesis_point: dict, depth: str = 'deep') -> dict:
    """
    Convenience function to support a thesis point.

    Args:
        ticker: Stock ticker
        thesis_point: Thesis point dict
        depth: 'quick', 'deep', or 'exhaustive'

    Returns:
        Full support analysis result
    """
    from agents.company_analyst_agent import CompanyAnalystAgent

    analyst = CompanyAnalystAgent(ticker)
    support_engine = ThesisSupport(ticker, analyst)

    return support_engine.support_thesis_point(thesis_point, depth=depth)
