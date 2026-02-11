"""
Historical event backtesting.
Run the pipeline on known past events and compare predictions to actual outcomes.
"""

import json
from datetime import datetime
from pathlib import Path

# Historical events with known outcomes
HISTORICAL_EVENTS = [
    {
        'id': 'export_controls_oct2022',
        'date': '2022-10-07',
        'news_input': (
            "The US Bureau of Industry and Security announces sweeping new export controls "
            "restricting the sale of advanced AI chips and semiconductor manufacturing equipment "
            "to China. The rules target chips with certain compute thresholds and restrict "
            "US persons from supporting Chinese chip development."
        ),
        'expected': {
            'NVDA': {
                'direction': 'negative',
                'primary_driver': 'datacenter_growth',
                'actual_impact': 'NVDA datacenter China revenue dropped ~$5B annually',
            },
            'ASML': {
                'direction': 'negative',
                'primary_driver': 'datacenter_growth',
                'actual_impact': 'ASML China orders restricted for advanced EUV',
            },
        },
    },
    {
        'id': 'nvidia_earnings_may2023',
        'date': '2023-05-24',
        'news_input': (
            "NVIDIA reports FQ1 2024 earnings with datacenter revenue of $4.28B, up 14% Q/Q, "
            "and guides FQ2 revenue to $11B, 50% above Wall Street consensus of $7.2B. "
            "CEO Jensen Huang declares 'a new computing era has begun' driven by generative AI demand."
        ),
        'expected': {
            'NVDA': {
                'direction': 'positive',
                'primary_driver': 'datacenter_growth',
                'actual_impact': 'Datacenter revenue accelerated to 4x Y/Y growth by FY2025',
            },
        },
    },
    {
        'id': 'tsmc_capex_jan2024',
        'date': '2024-01-18',
        'news_input': (
            "TSMC guides 2024 capex of $28-32B, above consensus, citing strong AI chip demand. "
            "Management notes N3 is ramping faster than N5 and CoWoS advanced packaging capacity "
            "is being doubled to meet NVIDIA and AMD demand."
        ),
        'expected': {
            'TSM': {
                'direction': 'positive',
                'primary_driver': 'datacenter_growth',
                'actual_impact': 'TSMC 2024 revenue grew 26% Y/Y driven by AI demand',
            },
            'ASML': {
                'direction': 'positive',
                'primary_driver': 'datacenter_growth',
                'actual_impact': 'ASML bookings surged on advanced node equipment demand',
            },
        },
    },
    {
        'id': 'deepseek_r1_jan2025',
        'date': '2025-01-20',
        'news_input': (
            "Chinese AI lab DeepSeek releases R1, an open-source reasoning model that matches "
            "GPT-4o performance while being trained on a fraction of the compute. The model was "
            "reportedly trained using older NVIDIA H800 chips (export-compliant). Markets react "
            "with a $600B semiconductor selloff led by NVIDIA."
        ),
        'expected': {
            'NVDA': {
                'direction': 'mixed',
                'primary_driver': 'datacenter_growth',
                'actual_impact': 'Initial selloff reversed; efficiency gains increase total AI spending',
            },
        },
    },
    {
        'id': 'chips_act_aug2022',
        'date': '2022-08-09',
        'news_input': (
            "President Biden signs the CHIPS and Science Act into law, providing $52.7B in "
            "semiconductor manufacturing subsidies and $24B in tax credits for chip fabrication "
            "in the United States."
        ),
        'expected': {
            'TSM': {
                'direction': 'positive',
                'primary_driver': 'gm_improvement_bps',
                'actual_impact': 'TSMC Arizona fab received CHIPS Act funding, though with higher costs',
            },
        },
    },
]


def run_backtest(pm_agent, events=None):
    """Run the pipeline on historical events and compare to actual outcomes.

    Args:
        pm_agent: PMAgent instance
        events: list of event dicts (defaults to HISTORICAL_EVENTS)

    Returns:
        List of backtest result dicts.
    """
    if events is None:
        events = HISTORICAL_EVENTS

    results = []
    for hist_event in events:
        print(f"\n{'='*70}")
        print(f"  BACKTEST: {hist_event['id']} ({hist_event['date']})")
        print(f"{'='*70}")

        try:
            # Run pipeline
            pipeline_result = pm_agent.run_full_pipeline(hist_event['news_input'])

            # Compare to expected
            bt_result = {
                'event_id': hist_event['id'],
                'date': hist_event['date'],
                'pipeline_ran': True,
                'comparisons': {},
            }

            for company, expected in hist_event['expected'].items():
                comparison = {
                    'expected_direction': expected['direction'],
                    'expected_driver': expected['primary_driver'],
                    'actual_impact': expected['actual_impact'],
                }

                # Check if pipeline produced a result for this company
                if pipeline_result and company == 'NVDA':
                    upside = pipeline_result.get('upside', 0)
                    if upside > 0:
                        comparison['predicted_direction'] = 'positive'
                    elif upside < 0:
                        comparison['predicted_direction'] = 'negative'
                    else:
                        comparison['predicted_direction'] = 'neutral'

                    comparison['predicted_upside'] = upside
                    comparison['direction_correct'] = (
                        comparison['predicted_direction'] == expected['direction']
                        or expected['direction'] == 'mixed'
                    )
                else:
                    comparison['predicted_direction'] = 'unknown'
                    comparison['direction_correct'] = None

                bt_result['comparisons'][company] = comparison

            results.append(bt_result)

        except Exception as e:
            print(f"  Error: {e}")
            results.append({
                'event_id': hist_event['id'],
                'pipeline_ran': False,
                'error': str(e),
            })

    return results


def print_backtest_summary(results: list):
    """Print a summary of backtest results."""
    print("\n" + "=" * 70)
    print("  BACKTEST SUMMARY")
    print("=" * 70)

    total = 0
    correct = 0
    for r in results:
        if not r.get('pipeline_ran'):
            print(f"  {r['event_id']}: FAILED ({r.get('error', 'unknown')})")
            continue

        for company, comp in r.get('comparisons', {}).items():
            total += 1
            direction_ok = comp.get('direction_correct')
            if direction_ok:
                correct += 1
            status = "CORRECT" if direction_ok else ("WRONG" if direction_ok is False else "N/A")
            print(f"  {r['event_id']} / {company}: {status} "
                  f"(expected={comp['expected_direction']}, "
                  f"predicted={comp.get('predicted_direction', '?')})")

    if total > 0:
        print(f"\n  Directional accuracy: {correct}/{total} = {correct/total:.0%}")
    print()
