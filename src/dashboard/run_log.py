"""Read ``data/runs/*.jsonl`` into structured events for the dashboard's log tab.

Kept free of ``streamlit`` imports so the parsing logic is unit-testable.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_RUNS_DIR = Path("data/runs")


@dataclass
class RunInfo:
    path: Path
    timestamp: str
    tag: str

    @property
    def label(self) -> str:
        return f"{self.timestamp} · {self.tag}"


@dataclass
class RunSummary:
    n_events: int = 0
    n_turns: int = 0
    n_tool_calls: int = 0
    tool_histogram: dict[str, int] = field(default_factory=dict)
    elapsed_ms: int = 0
    finished: bool = False
    model: str | None = None
    prompt_version: str | None = None


def list_runs(runs_dir: Path = DEFAULT_RUNS_DIR) -> list[RunInfo]:
    """Return run log files, newest first."""
    if not runs_dir.exists():
        return []
    return sorted(
        (_parse_filename(p) for p in runs_dir.glob("*.jsonl")),
        key=lambda r: r.timestamp,
        reverse=True,
    )


def _parse_filename(path: Path) -> RunInfo:
    stem = path.stem  # e.g. "20260424T113749_dm_drafts" or "20260424T101504"
    if "_" in stem:
        timestamp, tag = stem.split("_", 1)
    else:
        timestamp, tag = stem, "ingestion"
    return RunInfo(path=path, timestamp=timestamp, tag=tag)


def load_run(path: Path) -> list[dict[str, Any]]:
    """Load one JSONL run file into a list of event dicts."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize_run(events: list[dict[str, Any]]) -> RunSummary:
    if not events:
        return RunSummary()
    summary = RunSummary(n_events=len(events))
    histogram: Counter[str] = Counter()
    for e in events:
        event_type = e.get("event")
        if event_type == "assistant":
            summary.n_turns += 1
        elif event_type == "tool_call":
            summary.n_tool_calls += 1
            name = e.get("name")
            if name:
                histogram[name] += 1
        elif event_type == "finish":
            summary.finished = True
        elif event_type == "run_start":
            summary.model = e.get("model")
            summary.prompt_version = e.get("prompt_version")
    summary.tool_histogram = dict(histogram)
    summary.elapsed_ms = max(0, int(events[-1].get("t_ms", 0)) - int(events[0].get("t_ms", 0)))
    return summary
