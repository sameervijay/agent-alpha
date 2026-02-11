"""
Evaluation metrics for the Council of Agents system.
"""

from typing import List


def directional_accuracy(predictions: list, actuals: list) -> float:
    """Compute what fraction of predictions got the direction right.

    Args:
        predictions: list of dicts with 'direction' key ('positive', 'negative', 'neutral')
        actuals: list of dicts with 'direction' key

    Returns:
        Accuracy as float 0.0-1.0
    """
    if not predictions or len(predictions) != len(actuals):
        return 0.0

    correct = 0
    for pred, actual in zip(predictions, actuals):
        if pred.get('direction') == actual.get('direction'):
            correct += 1
        elif actual.get('direction') == 'mixed':
            correct += 1  # mixed counts as correct for any prediction
    return correct / len(predictions)


def magnitude_error(predictions: list, actuals: list) -> float:
    """Compute mean absolute error of magnitude predictions.

    Args:
        predictions: list of dicts with 'value' key (float)
        actuals: list of dicts with 'value' key (float)

    Returns:
        MAE as float
    """
    if not predictions or len(predictions) != len(actuals):
        return float('inf')

    errors = []
    for pred, actual in zip(predictions, actuals):
        pred_val = pred.get('value', 0)
        actual_val = actual.get('value', 0)
        errors.append(abs(pred_val - actual_val))
    return sum(errors) / len(errors)


def causal_graph_overlap(predicted_links: list, ground_truth_links: list) -> float:
    """Compute overlap between predicted and ground truth causal links.

    Uses (source_event, downstream_metric, affected_company, direction) as the key.

    Args:
        predicted_links: list of CausalLink dicts
        ground_truth_links: list of CausalLink dicts

    Returns:
        Overlap ratio (Jaccard-like) as float 0.0-1.0
    """
    def link_key(l):
        return (l.get('downstream_metric', ''),
                l.get('affected_company', ''),
                l.get('direction', ''))

    pred_keys = set(link_key(l) for l in predicted_links)
    truth_keys = set(link_key(l) for l in ground_truth_links)

    if not truth_keys:
        return 1.0 if not pred_keys else 0.0

    intersection = pred_keys & truth_keys
    union = pred_keys | truth_keys
    return len(intersection) / len(union) if union else 0.0


def source_grounding_rate(links: list) -> float:
    """Check what fraction of causal links have non-empty reasoning.

    Args:
        links: list of CausalLink dicts

    Returns:
        Grounding rate as float 0.0-1.0
    """
    if not links:
        return 0.0

    grounded = sum(1 for l in links if l.get('reasoning', '').strip())
    return grounded / len(links)


def compute_all_metrics(backtest_results: list, causal_graphs: list = None) -> dict:
    """Compute all evaluation metrics from backtest results.

    Args:
        backtest_results: output from backtest.run_backtest()
        causal_graphs: optional list of CausalGraph dicts for grounding check

    Returns:
        Dict with all metrics.
    """
    # Direction accuracy from backtest
    predictions = []
    actuals = []
    for r in backtest_results:
        if not r.get('pipeline_ran'):
            continue
        for company, comp in r.get('comparisons', {}).items():
            predictions.append({'direction': comp.get('predicted_direction', 'unknown')})
            actuals.append({'direction': comp.get('expected_direction', 'unknown')})

    metrics = {
        'directional_accuracy': directional_accuracy(predictions, actuals),
        'num_events_tested': len(backtest_results),
        'num_comparisons': len(predictions),
    }

    # Grounding rate from causal graphs
    if causal_graphs:
        all_links = []
        for graph in causal_graphs:
            all_links.extend(graph.get('links', []))
        metrics['source_grounding_rate'] = source_grounding_rate(all_links)
        metrics['num_causal_links'] = len(all_links)

    return metrics


def print_metrics(metrics: dict):
    """Print formatted evaluation metrics."""
    print("\n  EVALUATION METRICS")
    print("  " + "=" * 50)
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"  {key:<30} {value:.1%}")
        else:
            print(f"  {key:<30} {value}")
    print()
