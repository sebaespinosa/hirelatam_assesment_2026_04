"""Agent orchestration loop over OpenAI Chat Completions with function calling.

Agent owns routing; the handlers in ``src/agent/tools.py`` do the actual work.
Every turn — assistant message, each tool call, each tool result — is written
to ``data/runs/{timestamp}.jsonl`` for the dashboard's run-log viewer.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.agent.logger import RunLogger
from src.agent.tools import HANDLERS, TOOLS, ToolContext

# gpt-4o-mini truncates the classify fan-out and skips entire sources on runs of this size.
# gpt-4o follows the prompt's per-source sequencing reliably. Classifier stays on mini.
DEFAULT_MODEL = "gpt-4o"
PROMPT_PATH = Path("prompts/orchestrator.md")
_PROMPT_MARKER = "## System Prompt"
_VERSION_RE = re.compile(r"\*\*Version:\*\*\s*(\S+)")


class _OpenAIClient(Protocol):
    chat: Any  # OpenAI SDK doesn't ship a protocol; duck-type is fine.


def load_system_prompt() -> str:
    content = PROMPT_PATH.read_text()
    idx = content.find(_PROMPT_MARKER)
    if idx == -1:
        return content.strip()
    return content[idx + len(_PROMPT_MARKER) :].strip()


def load_prompt_version() -> str:
    content = PROMPT_PATH.read_text()
    match = _VERSION_RE.search(content)
    return match.group(1) if match else "unknown"


@dataclass
class RunResult:
    summary: dict[str, Any] | None
    turns: int
    tool_calls: int
    finished: bool
    log_path: Path


def _assistant_to_message(message: Any) -> dict[str, Any]:
    """Convert an OpenAI ChatCompletionMessage into an append-friendly dict."""
    payload: dict[str, Any] = {
        "role": "assistant",
        "content": message.content,
    }
    if getattr(message, "tool_calls", None):
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in message.tool_calls
        ]
    return payload


def _execute_tool_call(
    call: Any,
    *,
    ctx: ToolContext,
    logger: RunLogger,
    turn: int,
) -> dict[str, Any]:
    name = call.function.name
    raw_args = call.function.arguments
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        result = {"error": f"invalid JSON arguments: {exc}", "code": "validation_error"}
        logger.log(
            "tool_call",
            turn=turn,
            tool_call_id=call.id,
            name=name,
            args=None,
            result=result,
            raw_args=raw_args,
        )
        return result

    handler = HANDLERS.get(name)
    if handler is None:
        result = {"error": f"unknown tool {name!r}", "code": "validation_error"}
    else:
        t0 = time.monotonic()
        try:
            result = handler(args, ctx)
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"{type(exc).__name__}: {exc}", "code": "handler_exception"}
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.log(
            "tool_call",
            turn=turn,
            tool_call_id=call.id,
            name=name,
            args=args,
            result=result,
            elapsed_ms=elapsed_ms,
        )
        return result
    logger.log("tool_call", turn=turn, tool_call_id=call.id, name=name, args=args, result=result)
    return result


def run_agent(
    *,
    conn: sqlite3.Connection | None,
    client: _OpenAIClient | None = None,
    model: str = DEFAULT_MODEL,
    max_turns: int = 30,
    persist: bool = True,
    classify_fn: Any = None,
    runs_dir: Path | None = None,
) -> RunResult:
    """Run the orchestrator.

    Pass a fake ``client`` in tests (duck-typed ``chat.completions.create``).
    Pass ``classify_fn`` to stub the classifier.
    """
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    logger = RunLogger(runs_dir=runs_dir) if runs_dir else RunLogger()
    ctx_kwargs: dict[str, Any] = {"conn": conn, "persist": persist}
    if classify_fn is not None:
        ctx_kwargs["classify_fn"] = classify_fn
    ctx = ToolContext(**ctx_kwargs)

    system_prompt = load_system_prompt()
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    logger.log(
        "run_start",
        model=model,
        prompt_version=load_prompt_version(),
        max_turns=max_turns,
        persist=persist,
    )

    tool_call_count = 0
    turn = 0
    for turn in range(1, max_turns + 1):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            parallel_tool_calls=True,
        )
        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason
        usage = getattr(response, "usage", None)

        assistant_payload = _assistant_to_message(message)
        messages.append(assistant_payload)
        logger.log(
            "assistant",
            turn=turn,
            finish_reason=finish_reason,
            content=message.content,
            tool_calls=len(assistant_payload.get("tool_calls", []) or []),
            tokens_in=getattr(usage, "prompt_tokens", None),
            tokens_out=getattr(usage, "completion_tokens", None),
        )

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            logger.log("assistant_text_break", turn=turn, content=message.content)
            break

        for call in tool_calls:
            tool_call_count += 1
            result = _execute_tool_call(call, ctx=ctx, logger=logger, turn=turn)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )

        if ctx.finished:
            logger.log("finish", turn=turn, summary=ctx.finish_summary)
            return RunResult(
                summary=ctx.finish_summary,
                turns=turn,
                tool_calls=tool_call_count,
                finished=True,
                log_path=logger.path,
            )
    else:
        logger.log("max_turns_reached", turns=max_turns, tool_calls=tool_call_count)

    return RunResult(
        summary=ctx.finish_summary,
        turns=turn,
        tool_calls=tool_call_count,
        finished=ctx.finished,
        log_path=logger.path,
    )
