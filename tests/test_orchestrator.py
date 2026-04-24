"""Integration-style tests for the orchestrator loop using a stubbed OpenAI client."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agent.orchestrator import load_prompt_version, load_system_prompt, run_agent
from src.classifier import ClassificationResult
from src.db.repo import list_companies


@dataclass
class _ToolCall:
    id: str
    function: Any


@dataclass
class _FunctionStub:
    name: str
    arguments: str


@dataclass
class _Message:
    content: str | None
    tool_calls: list[_ToolCall] | None


@dataclass
class _Choice:
    message: _Message
    finish_reason: str


@dataclass
class _Usage:
    prompt_tokens: int = 100
    completion_tokens: int = 10


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage


class ScriptedClient:
    """Duck-typed OpenAI client. Returns scripted responses per call."""

    def __init__(self, script: list[_Message]) -> None:
        self._script = list(script)
        self.chat = _Chat(self)
        self.captured_requests: list[dict[str, Any]] = []

    def _next(self, **kwargs: Any) -> _Response:
        if not self._script:
            raise RuntimeError("scripted client exhausted")
        message = self._script.pop(0)
        self.captured_requests.append(kwargs)
        finish_reason = "tool_calls" if message.tool_calls else "stop"
        return _Response(
            choices=[_Choice(message=message, finish_reason=finish_reason)],
            usage=_Usage(),
        )


class _Chat:
    def __init__(self, client: ScriptedClient) -> None:
        self.completions = _Completions(client)


class _Completions:
    def __init__(self, client: ScriptedClient) -> None:
        self._client = client

    def create(self, **kwargs: Any) -> _Response:
        return self._client._next(**kwargs)


def _tool_call(call_id: str, name: str, args: dict[str, Any]) -> _ToolCall:
    return _ToolCall(
        id=call_id,
        function=_FunctionStub(name=name, arguments=json.dumps(args)),
    )


def _stub_classify(**_: Any) -> ClassificationResult:
    return ClassificationResult(
        is_launch=True, confidence=0.95, launch_type="product", reasoning="stub"
    )


# --- prompt loader ---------------------------------------------------------


def test_system_prompt_loaded_without_metadata_header() -> None:
    prompt = load_system_prompt()
    assert "You are the orchestrator" in prompt
    assert "**Version:**" not in prompt
    assert "# Orchestrator" not in prompt


def test_prompt_version_matches_file() -> None:
    assert load_prompt_version() == "v1"


# --- orchestrator loop ----------------------------------------------------


def test_run_agent_happy_path_persists_and_finishes(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    # Turn 1: agent calls persist_company for a single YC-style item.
    # Turn 2: agent calls finish.
    company_args = {"company": {"name": "Alpha", "website": "https://alpha.example.com"}}
    finish_args = {
        "summary": {"by_source": {"mock_yc": {"fetched": 1, "persisted": 1, "errors": 0}}}
    }
    script = [
        _Message(content=None, tool_calls=[_tool_call("call_1", "persist_company", company_args)]),
        _Message(content=None, tool_calls=[_tool_call("call_2", "finish", finish_args)]),
    ]
    client = ScriptedClient(script)
    result = run_agent(
        conn=db,
        client=client,
        runs_dir=tmp_path / "runs",
        classify_fn=_stub_classify,
    )
    assert result.finished is True
    assert result.summary == finish_args["summary"]
    assert result.turns == 2
    assert result.tool_calls == 2

    companies = list_companies(db)
    assert len(companies) == 1
    assert companies[0].name == "Alpha"


def test_run_agent_validation_error_does_not_crash(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    # Agent passes an invalid persist_company arg (missing "name"), sees the validation error,
    # then calls finish. The loop should complete normally.
    bad_args = {"company": {}}
    finish_args = {"summary": {"by_source": {}}}
    script = [
        _Message(content=None, tool_calls=[_tool_call("call_1", "persist_company", bad_args)]),
        _Message(content=None, tool_calls=[_tool_call("call_2", "finish", finish_args)]),
    ]
    result = run_agent(conn=db, client=ScriptedClient(script), runs_dir=tmp_path / "runs")
    assert result.finished is True
    assert list_companies(db) == []

    log_events = [json.loads(line) for line in result.log_path.read_text().splitlines()]
    tool_events = [e for e in log_events if e["event"] == "tool_call"]
    assert any(e.get("result", {}).get("code") == "validation_error" for e in tool_events)


def test_run_agent_parallel_tool_calls_in_one_turn(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    # Single assistant message issuing three parallel persist_company calls, then finish.
    calls = [
        _tool_call("c1", "persist_company", {"company": {"name": "A"}}),
        _tool_call("c2", "persist_company", {"company": {"name": "B"}}),
        _tool_call("c3", "persist_company", {"company": {"name": "C"}}),
    ]
    finish_args = {"summary": {"by_source": {"mock_yc": {"fetched": 3, "persisted": 3}}}}
    script = [
        _Message(content=None, tool_calls=calls),
        _Message(content=None, tool_calls=[_tool_call("c4", "finish", finish_args)]),
    ]
    result = run_agent(conn=db, client=ScriptedClient(script), runs_dir=tmp_path / "runs")
    assert result.tool_calls == 4
    names = {c.name for c in list_companies(db)}
    assert names == {"A", "B", "C"}


def test_run_agent_max_turns_without_finish(db: sqlite3.Connection, tmp_path: Path) -> None:
    # An infinite loop of trivial tool calls; the max_turns cap must end the run.
    script = [
        _Message(
            content=None,
            tool_calls=[_tool_call(f"c{i}", "persist_company", {"company": {"name": f"A{i}"}})],
        )
        for i in range(20)
    ]
    result = run_agent(
        conn=db,
        client=ScriptedClient(script),
        runs_dir=tmp_path / "runs",
        max_turns=3,
    )
    assert result.finished is False
    assert result.turns == 3


def test_run_agent_assistant_text_without_tools_breaks_loop(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    script = [_Message(content="done", tool_calls=None)]
    result = run_agent(conn=db, client=ScriptedClient(script), runs_dir=tmp_path / "runs")
    assert result.turns == 1
    assert result.finished is False


def test_run_agent_logs_cover_run_lifecycle(db: sqlite3.Connection, tmp_path: Path) -> None:
    script = [
        _Message(
            content=None,
            tool_calls=[_tool_call("c1", "finish", {"summary": {"by_source": {}}})],
        )
    ]
    result = run_agent(conn=db, client=ScriptedClient(script), runs_dir=tmp_path / "runs")
    events = [json.loads(line)["event"] for line in result.log_path.read_text().splitlines()]
    assert events[0] == "run_start"
    assert "assistant" in events
    assert "tool_call" in events
    assert events[-1] == "finish"
