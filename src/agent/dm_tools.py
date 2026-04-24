"""Tool definitions + handlers for the Phase 7 DM-draft pass.

Three tools:
- ``list_underperforming_launches`` — wraps ``src.agent.thresholds`` and
  returns launches below their source's P25, with company + contact context.
- ``persist_dm_draft`` — validates agent-generated subject/body/tone into a
  ``DmDraft`` and writes it. Auto-injects ``prompt_version`` from the prompt
  file; the agent does not need to know it.
- ``finish`` — standard run terminator.

The agent itself drafts the DM text (subject + body) following ``prompts/dm_draft.md``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.agent.thresholds import (
    DEFAULT_MAX_COUNT,
    DEFAULT_WINDOW_DAYS,
    list_underperforming_launches,
)
from src.agent.tools import ToolContext
from src.db.repo import insert_dm_draft
from src.models import DmDraft

DM_PROMPT_PATH = Path("prompts/dm_draft.md")
_PROMPT_MARKER = "## System Prompt"
_VERSION_RE = re.compile(r"\*\*Version:\*\*\s*(\S+)")


def load_dm_system_prompt() -> str:
    content = DM_PROMPT_PATH.read_text()
    idx = content.find(_PROMPT_MARKER)
    return content[idx + len(_PROMPT_MARKER) :].strip() if idx != -1 else content.strip()


def load_dm_prompt_version() -> str:
    content = DM_PROMPT_PATH.read_text()
    match = _VERSION_RE.search(content)
    return match.group(1) if match else "unknown"


# --- handlers --------------------------------------------------------------


def handle_list_underperforming_launches(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    if ctx.conn is None:
        return {"error": "no database connection", "code": "runtime_error", "launches": []}
    window_days = int(args.get("window_days") or DEFAULT_WINDOW_DAYS)
    max_count = int(args.get("max_count") or DEFAULT_MAX_COUNT)
    launches = list_underperforming_launches(
        ctx.conn,
        window_days=window_days,
        max_count=max_count,
    )
    return {"launches": launches}


def handle_persist_dm_draft(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    data = {
        "launch_id": args.get("launch_id"),
        "subject": args.get("subject"),
        "body": args.get("body"),
        "tone": args.get("tone"),
        "prompt_version": load_dm_prompt_version(),
    }
    try:
        draft = DmDraft.model_validate(data)
    except ValidationError as exc:
        return {"error": str(exc), "code": "validation_error", "model": "DmDraft"}

    if not ctx.persist or ctx.conn is None:
        return {"dry_run": True, "launch_id": draft.launch_id}

    stored = insert_dm_draft(ctx.conn, draft)
    return {"dm_draft_id": stored.id, "launch_id": draft.launch_id}


def handle_finish(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    summary = args.get("summary")
    if not isinstance(summary, dict):
        return {"error": "summary must be an object", "code": "validation_error"}
    ctx.finished = True
    ctx.finish_summary = summary
    return {"ok": True}


DM_HANDLERS: dict[str, Callable[[dict[str, Any], ToolContext], dict[str, Any]]] = {
    "list_underperforming_launches": handle_list_underperforming_launches,
    "persist_dm_draft": handle_persist_dm_draft,
    "finish": handle_finish,
}


# --- OpenAI tool definitions -----------------------------------------------


DM_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_underperforming_launches",
            "description": (
                "Return launches with engagement_score below their source's P25 "
                "within the recent window. Call this first."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "window_days": {"type": "integer", "minimum": 7, "maximum": 365},
                    "max_count": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persist_dm_draft",
            "description": (
                "Write one DM draft for a launch. The runtime injects "
                "prompt_version automatically."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "launch_id": {"type": "integer"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "tone": {"type": "string"},
                },
                "required": ["launch_id", "subject", "body", "tone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "End the run with a summary dict.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"summary": {"type": "object"}},
                "required": ["summary"],
            },
        },
    },
]
