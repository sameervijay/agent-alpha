"""
Test script to process expert call transcripts with the company analyst agent.

Usage:
    python3 test_expert_call.py CDNS "Expert calls/Former Director at Cadence Design Systems..."
    python3 test_expert_call.py --ticker CDNS --file "path/to/expert/call.docx"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents.company_analyst_agent import CompanyAnalystAgent
from docx import Document


def read_docx(filepath: str) -> str:
    """Extract text from a .docx file."""
    doc = Document(filepath)
    text_parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            text_parts.append(text)
    return "\n".join(text_parts)


def read_text_file(filepath: str) -> str:
    """Read a plain text file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def load_expert_call(filepath: str) -> str:
    """Load expert call from file (supports .docx and .txt)."""
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f"Expert call file not found: {filepath}")

    if path.suffix.lower() == '.docx':
        return read_docx(filepath)
    elif path.suffix.lower() in ['.txt', '.md']:
        return read_text_file(filepath)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}. Use .docx or .txt")


def process_expert_call(ticker: str, filepath: str):
    """Process an expert call and update analyst view."""
    print("=" * 70)
    print(f"  PROCESSING EXPERT CALL: {ticker}")
    print("=" * 70)

    # Load expert call
    print(f"\nLoading expert call from: {filepath}")
    try:
        expert_call_text = load_expert_call(filepath)
        print(f"  Loaded {len(expert_call_text)} characters")
    except Exception as e:
        print(f"  Error loading file: {e}")
        return

    # Initialize analyst
    analyst = CompanyAnalystAgent(ticker)

    # Check if view exists
    if not analyst.has_view:
        print(f"\n  ERROR: No existing view for {ticker}.")
        print(f"  Please run ramp mode first: python3 test_cdns_analyst.py --ramp")
        return

    # Show current view
    print(f"\n--- Current View (Before Expert Call) ---")
    view_before = analyst._load_view()
    print(f"  Summary: {view_before.summary[:120]}...")
    print(f"  Confidence: {view_before.confidence:.0%}")
    print(f"  Last updated: {view_before.last_updated}")

    # Process expert call
    print(f"\n--- Processing Expert Call ---")
    updated_view = analyst.learn_from_expert_call(expert_call_text)

    if updated_view is None:
        print("  Failed to process expert call.")
        return

    # Show updated view
    print(f"\n--- Updated View (After Expert Call) ---")
    print(f"  Summary: {updated_view.summary[:120]}...")
    print(f"  Confidence: {updated_view.confidence:.0%}")
    print(f"  Last updated: {updated_view.last_updated}")

    # Compare changes
    if updated_view.confidence != view_before.confidence:
        delta = updated_view.confidence - view_before.confidence
        print(f"  Confidence change: {delta:+.1%}")

    # Show driver changes
    changed_drivers = []
    for driver in updated_view.baseline_drivers:
        if driver not in view_before.baseline_drivers:
            changed_drivers.append(driver)
        else:
            for period, val in updated_view.baseline_drivers[driver].items():
                old_val = view_before.baseline_drivers[driver].get(period)
                if old_val != val:
                    changed_drivers.append(f"{driver}[{period}]")

    if changed_drivers:
        print(f"\n  Driver changes: {', '.join(changed_drivers[:5])}")
        if len(changed_drivers) > 5:
            print(f"    ... and {len(changed_drivers) - 5} more")
    else:
        print(f"\n  No driver changes made.")

    print("\n" + "=" * 70)
    print("  Expert call processing complete.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='Process expert call transcripts with company analyst agent'
    )
    parser.add_argument('--ticker', type=str, required=True,
                       help='Company ticker (e.g., CDNS)')
    parser.add_argument('--file', type=str, required=True,
                       help='Path to expert call file (.docx or .txt)')
    args = parser.parse_args()

    process_expert_call(args.ticker, args.file)


if __name__ == '__main__':
    main()
