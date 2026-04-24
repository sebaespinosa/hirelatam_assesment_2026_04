"""Run the launch classifier over a JSONL eval set and print metrics.

Usage:
    python -m evals.run_classifier                            # default path
    python -m evals.run_classifier evals/launch_classifier.jsonl
    python -m evals.run_classifier --verbose                  # also prints TP/TN lines

Targets (from docs/launch_definition.md §7):
    Precision on positives >= 0.90
    Recall on positives    >= 0.85
    Negative accuracy      >= 0.90
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.classifier import ClassificationResult, classify_launch

DEFAULT_EVAL_PATH = Path("evals/launch_classifier.jsonl")
PLACEHOLDER = "[PASTE TEXT]"
TARGETS = {"precision": 0.90, "recall": 0.85, "neg_accuracy": 0.90}


@dataclass
class Outcome:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    false_positives: list[tuple[str, ClassificationResult]] = field(default_factory=list)
    false_negatives: list[tuple[str, ClassificationResult]] = field(default_factory=list)

    @property
    def evaluated(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def negative_accuracy(self) -> float:
        return self.tn / (self.tn + self.fp) if (self.tn + self.fp) else 0.0


def _load_entries(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _metadata(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "handle": entry.get("handle"),
        "url": entry.get("url"),
        "media": entry.get("media"),
        "likes": entry.get("likes"),
        "reposts": entry.get("reposts"),
    }


def run(path: Path, *, verbose: bool = False) -> Outcome:
    outcome = Outcome()
    entries = _load_entries(path)
    for entry in entries:
        post_text = entry.get("post_text", "") or ""
        if PLACEHOLDER in post_text or not post_text.strip():
            outcome.skipped += 1
            continue

        expected = bool(entry["expected"]["is_launch"])
        entry_id = entry.get("id", "?")
        try:
            result = classify_launch(post_text=post_text, metadata=_metadata(entry))
        except Exception as exc:  # noqa: BLE001 — we want to keep going on single failures
            outcome.errors.append((entry_id, f"{type(exc).__name__}: {exc}"))
            continue

        if result.is_launch and expected:
            outcome.tp += 1
            if verbose:
                print(f"TP {entry_id}: {result.reasoning}")
        elif result.is_launch and not expected:
            outcome.fp += 1
            outcome.false_positives.append((entry_id, result))
            print(f"FP {entry_id}: {result.reasoning}")
        elif not result.is_launch and not expected:
            outcome.tn += 1
            if verbose:
                print(f"TN {entry_id}: {result.reasoning}")
        else:
            outcome.fn += 1
            outcome.false_negatives.append((entry_id, result))
            print(f"FN {entry_id}: {result.reasoning}")

    return outcome


def _format_metric(name: str, value: float, target: float) -> str:
    ok = "PASS" if value >= target else "FAIL"
    return f"{name:<16}{value:>6.3f}   target >= {target:.2f}   {ok}"


def print_report(outcome: Outcome) -> int:
    print()
    print(f"Evaluated:       {outcome.evaluated}")
    print(f"  true positive  {outcome.tp}")
    print(f"  false positive {outcome.fp}")
    print(f"  true negative  {outcome.tn}")
    print(f"  false negative {outcome.fn}")
    if outcome.skipped:
        print(f"Skipped:         {outcome.skipped} (placeholder post_text)")
    if outcome.errors:
        print(f"Errors:          {len(outcome.errors)}")
        for entry_id, msg in outcome.errors:
            print(f"  {entry_id}: {msg}")
    print()
    print(_format_metric("Precision", outcome.precision, TARGETS["precision"]))
    print(_format_metric("Recall", outcome.recall, TARGETS["recall"]))
    print(_format_metric("Neg accuracy", outcome.negative_accuracy, TARGETS["neg_accuracy"]))

    hit = (
        outcome.precision >= TARGETS["precision"]
        and outcome.recall >= TARGETS["recall"]
        and outcome.negative_accuracy >= TARGETS["neg_accuracy"]
    )
    return 0 if hit else 1


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", type=Path, nargs="?", default=DEFAULT_EVAL_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"eval set not found: {args.path}", file=sys.stderr)
        return 2

    t0 = time.monotonic()
    outcome = run(args.path, verbose=args.verbose)
    elapsed = time.monotonic() - t0

    exit_code = print_report(outcome)
    print(f"\nElapsed: {elapsed:.1f}s")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
