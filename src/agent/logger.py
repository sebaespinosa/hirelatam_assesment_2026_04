"""Append-only JSONL logger for agent runs. Read by the Phase 8 dashboard."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEFAULT_RUNS_DIR = Path("data/runs")


class RunLogger:
    """One instance per agent run. Writes one line per event to ``runs_dir/{ts}.jsonl``."""

    def __init__(self, *, runs_dir: Path = DEFAULT_RUNS_DIR, tag: str | None = None) -> None:
        runs_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%dT%H%M%S")
        name = f"{ts}_{tag}.jsonl" if tag else f"{ts}.jsonl"
        self.path = runs_dir / name
        self._seq = 0
        self._t0 = time.monotonic()

    def log(self, event: str, **fields: Any) -> None:
        self._seq += 1
        record = {
            "seq": self._seq,
            "t_ms": int((time.monotonic() - self._t0) * 1000),
            "event": event,
            **fields,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
