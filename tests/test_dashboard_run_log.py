from __future__ import annotations

import json
from pathlib import Path

from src.dashboard.run_log import list_runs, load_run, summarize_run


def _write_run(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events))


# --- list_runs ------------------------------------------------------------


def test_list_runs_empty_dir(tmp_path: Path) -> None:
    assert list_runs(tmp_path) == []


def test_list_runs_missing_dir_is_empty(tmp_path: Path) -> None:
    assert list_runs(tmp_path / "does_not_exist") == []


def test_list_runs_sorted_newest_first(tmp_path: Path) -> None:
    (tmp_path / "20260101T000000.jsonl").write_text("")
    (tmp_path / "20260301T120000_enrichment.jsonl").write_text("")
    (tmp_path / "20260201T120000_dm_drafts.jsonl").write_text("")
    runs = list_runs(tmp_path)
    timestamps = [r.timestamp for r in runs]
    assert timestamps == ["20260301T120000", "20260201T120000", "20260101T000000"]


def test_list_runs_infers_tag_from_filename(tmp_path: Path) -> None:
    (tmp_path / "20260424T113749.jsonl").write_text("")
    (tmp_path / "20260424T113749_enrichment.jsonl").write_text("")
    runs = list_runs(tmp_path)
    tags = {r.tag for r in runs}
    assert tags == {"ingestion", "enrichment"}


# --- load_run -------------------------------------------------------------


def test_load_run_parses_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    _write_run(
        path,
        [
            {"event": "run_start", "t_ms": 0, "model": "gpt-4o"},
            {"event": "finish", "t_ms": 1000, "summary": {}},
        ],
    )
    events = load_run(path)
    assert [e["event"] for e in events] == ["run_start", "finish"]


def test_load_run_missing_file(tmp_path: Path) -> None:
    assert load_run(tmp_path / "nope.jsonl") == []


def test_load_run_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    path.write_text('{"event":"a"}\n\n{"event":"b"}\n\n')
    events = load_run(path)
    assert [e["event"] for e in events] == ["a", "b"]


# --- summarize_run --------------------------------------------------------


def test_summarize_run_counts_turns_and_tools() -> None:
    events = [
        {"event": "run_start", "t_ms": 0, "model": "gpt-4o", "prompt_version": "v1"},
        {"event": "assistant", "turn": 1, "t_ms": 100},
        {"event": "tool_call", "turn": 1, "name": "fetch_producthunt", "t_ms": 120},
        {"event": "tool_call", "turn": 1, "name": "load_mock_source", "t_ms": 140},
        {"event": "assistant", "turn": 2, "t_ms": 200},
        {"event": "tool_call", "turn": 2, "name": "classify_launch", "t_ms": 210},
        {"event": "tool_call", "turn": 2, "name": "classify_launch", "t_ms": 220},
        {"event": "finish", "turn": 3, "t_ms": 300, "summary": {}},
    ]
    summary = summarize_run(events)
    assert summary.n_turns == 2
    assert summary.n_tool_calls == 4
    assert summary.tool_histogram == {
        "fetch_producthunt": 1,
        "load_mock_source": 1,
        "classify_launch": 2,
    }
    assert summary.finished is True
    assert summary.elapsed_ms == 300
    assert summary.model == "gpt-4o"
    assert summary.prompt_version == "v1"


def test_summarize_run_empty_events() -> None:
    summary = summarize_run([])
    assert summary.n_events == 0
    assert summary.n_turns == 0
    assert summary.finished is False


def test_summarize_run_not_finished_if_no_finish_event() -> None:
    events = [
        {"event": "run_start", "t_ms": 0},
        {"event": "assistant", "turn": 1, "t_ms": 10},
        {"event": "max_turns_reached", "t_ms": 20},
    ]
    summary = summarize_run(events)
    assert summary.finished is False
