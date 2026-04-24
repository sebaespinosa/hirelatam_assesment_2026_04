"""Tool definitions + handlers for the Phase 5 orchestrator.

Each tool has three pieces:
- A JSON Schema (``TOOLS``) that OpenAI sees and the model calls.
- A handler function ``handle_{name}(args, ctx)`` that executes the tool locally.
- A dispatch mapping ``HANDLERS``.

Handlers return JSON-serializable dicts. Pydantic validation failures are
caught and returned as ``{"error": ..., "code": "validation_error"}`` so the
agent can self-correct on the next turn instead of crashing the loop.

Handlers do not manage retries — the orchestrator does. Handlers do not decide
whether to classify or persist — the orchestrator does. Handlers do one thing:
the thing named in the tool spec.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.classifier import ClassificationResult, classify_launch
from src.db.repo import insert_funding, insert_launch, upsert_company
from src.models import Company, FundingRound, Launch
from src.sources.mocks import (
    MOCK_CRUNCHBASE,
    MOCK_LINKEDIN,
    MOCK_SOURCES,
    MOCK_X,
    MOCK_YC,
    load_seed,
    normalize_crunchbase,
    normalize_linkedin,
    normalize_x,
    normalize_yc,
)
from src.sources.producthunt import (
    ProductHuntClient,
    load_snapshot,
    normalize_post,
    save_snapshot,
)

ClassifyFn = Callable[..., ClassificationResult]


@dataclass
class ToolContext:
    """Runtime state passed to every handler."""

    conn: sqlite3.Connection | None
    persist: bool = True
    classify_fn: ClassifyFn = classify_launch
    seed_dir: Path = Path("data/seed")
    finished: bool = False
    finish_summary: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Bundle helpers: convert Pydantic models to/from JSON-friendly bundle dicts.
# ---------------------------------------------------------------------------


def _company_to_dict(company: Company) -> dict[str, Any]:
    return {
        "name": company.name,
        "website": company.website,
        "description": company.description,
    }


def _launch_to_dict(launch: Launch) -> dict[str, Any]:
    return {
        "source": launch.source,
        "source_id": launch.source_id,
        "title": launch.title,
        "url": launch.url,
        "posted_at": launch.posted_at.isoformat(),
        "engagement_score": launch.engagement_score,
        "engagement_breakdown": launch.engagement_breakdown,
        "raw_payload": launch.raw_payload,
    }


def _funding_to_dict(round_: FundingRound) -> dict[str, Any]:
    return {
        "source": round_.source,
        "source_id": round_.source_id,
        "amount_usd": round_.amount_usd,
        "round_type": round_.round_type,
        "announced_at": round_.announced_at.isoformat(),
        "investors": round_.investors,
        "raw_payload": round_.raw_payload,
    }


def _bundle_launch(company: Company, launch: Launch) -> dict[str, Any]:
    return {"company": _company_to_dict(company), "launch": _launch_to_dict(launch)}


def _bundle_funding(company: Company, round_: FundingRound) -> dict[str, Any]:
    return {"company": _company_to_dict(company), "funding": _funding_to_dict(round_)}


def _bundle_company(company: Company) -> dict[str, Any]:
    return {"company": _company_to_dict(company)}


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_fetch_producthunt(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    days = int(args.get("days", 7))
    limit = int(args.get("limit", 20))
    try:
        with ProductHuntClient() as client:
            posted_after = datetime.now(UTC) - timedelta(days=days)
            nodes = client.fetch_posts(
                posted_after=posted_after,
                first=min(limit, 20),
                max_pages=5,
            )
        save_snapshot(nodes)
    except Exception as exc:  # noqa: BLE001
        try:
            nodes = load_snapshot()
        except FileNotFoundError:
            return {
                "error": f"live fetch failed and no snapshot available: {exc}",
                "code": "fetch_error",
                "posts": [],
            }
    nodes = nodes[:limit]
    posts: list[dict[str, Any]] = []
    errors: list[str] = []
    for node in nodes:
        try:
            company, launch = normalize_post(node)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{node.get('id', '?')}: {exc}")
            continue
        posts.append(_bundle_launch(company, launch))
    return {"posts": posts, "errors": errors}


def handle_load_mock_source(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    source = args.get("source")
    if source not in MOCK_SOURCES:
        return {
            "error": f"unknown source {source!r}; expected one of {list(MOCK_SOURCES)}",
            "code": "validation_error",
            "items": [],
        }
    try:
        nodes = load_seed(source, seed_dir=ctx.seed_dir)
    except FileNotFoundError as exc:
        return {"error": str(exc), "code": "fetch_error", "items": []}

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for node in nodes:
        try:
            if source == MOCK_X:
                company, launch = normalize_x(node)
                items.append(_bundle_launch(company, launch))
            elif source == MOCK_LINKEDIN:
                company, launch = normalize_linkedin(node)
                items.append(_bundle_launch(company, launch))
            elif source == MOCK_CRUNCHBASE:
                company, round_ = normalize_crunchbase(node)
                items.append(_bundle_funding(company, round_))
            elif source == MOCK_YC:
                company = normalize_yc(node)
                items.append(_bundle_company(company))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{node.get('source_id', '?')}: {exc}")
    return {"items": items, "errors": errors}


def handle_classify_launch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    post_text = args.get("post_text")
    metadata = args.get("metadata") or {}
    if not isinstance(post_text, str) or not post_text.strip():
        return {"error": "post_text must be a non-empty string", "code": "validation_error"}
    try:
        result = ctx.classify_fn(post_text=post_text, metadata=metadata)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}", "code": "classifier_error"}
    return result.model_dump()


def _resolve_pydantic(
    cls: type,
    data: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any] | None]:
    """Validate a dict into a Pydantic model. Returns (model, error) — only one is non-None."""
    payload = {**data, **(overrides or {})}
    try:
        return cls.model_validate(payload), None
    except ValidationError as exc:
        return None, {
            "error": str(exc),
            "code": "validation_error",
            "model": cls.__name__,
        }


def handle_persist_launch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    company_data = args.get("company") or {}
    launch_data = args.get("launch") or {}
    classification_data = args.get("classification")

    company, err = _resolve_pydantic(Company, company_data)
    if err:
        return err
    launch_with_placeholder, err = _resolve_pydantic(
        Launch, launch_data, overrides={"company_id": -1}
    )
    if err:
        return err

    classification_dump: dict[str, Any] | None = None
    if classification_data is not None:
        result, err = _resolve_pydantic(ClassificationResult, classification_data)
        if err:
            return err
        if not result.is_launch:
            return {
                "error": "refusing to persist: classification.is_launch is false",
                "code": "policy_error",
            }
        classification_dump = result.model_dump()

    if classification_dump is not None:
        launch_with_placeholder.raw_payload["_classification"] = classification_dump

    if not ctx.persist or ctx.conn is None:
        return {"dry_run": True, "launch_source_id": launch_with_placeholder.source_id}

    stored_company = upsert_company(ctx.conn, company)
    assert stored_company.id is not None
    launch_with_placeholder.company_id = stored_company.id
    stored_launch = insert_launch(ctx.conn, launch_with_placeholder)
    return {"company_id": stored_company.id, "launch_id": stored_launch.id}


def handle_persist_funding(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    company_data = args.get("company") or {}
    funding_data = args.get("funding") or {}

    company, err = _resolve_pydantic(Company, company_data)
    if err:
        return err
    round_with_placeholder, err = _resolve_pydantic(
        FundingRound, funding_data, overrides={"company_id": -1}
    )
    if err:
        return err

    if not ctx.persist or ctx.conn is None:
        return {"dry_run": True, "funding_source_id": round_with_placeholder.source_id}

    stored_company = upsert_company(ctx.conn, company)
    assert stored_company.id is not None
    round_with_placeholder.company_id = stored_company.id
    stored_round = insert_funding(ctx.conn, round_with_placeholder)
    return {"company_id": stored_company.id, "funding_id": stored_round.id}


def handle_persist_company(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    company_data = args.get("company") or {}
    company, err = _resolve_pydantic(Company, company_data)
    if err:
        return err

    if not ctx.persist or ctx.conn is None:
        return {"dry_run": True, "company_name": company.name}

    stored_company = upsert_company(ctx.conn, company)
    return {"company_id": stored_company.id}


def handle_finish(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    summary = args.get("summary")
    if not isinstance(summary, dict):
        return {"error": "summary must be an object", "code": "validation_error"}
    ctx.finished = True
    ctx.finish_summary = summary
    return {"ok": True}


HANDLERS: dict[str, Callable[[dict[str, Any], ToolContext], dict[str, Any]]] = {
    "fetch_producthunt": handle_fetch_producthunt,
    "load_mock_source": handle_load_mock_source,
    "classify_launch": handle_classify_launch,
    "persist_launch": handle_persist_launch,
    "persist_funding": handle_persist_funding,
    "persist_company": handle_persist_company,
    "finish": handle_finish,
}


# ---------------------------------------------------------------------------
# OpenAI tool definitions
# ---------------------------------------------------------------------------


_COMPANY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "website": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["name"],
}

_LAUNCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source": {"type": "string"},
        "source_id": {"type": "string"},
        "title": {"type": "string"},
        "url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "posted_at": {"type": "string"},
        "engagement_score": {"type": "number"},
        "engagement_breakdown": {"type": "object"},
        "raw_payload": {"type": "object"},
    },
    "required": ["source", "source_id", "title", "posted_at"],
}

_FUNDING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source": {"type": "string"},
        "source_id": {"type": "string"},
        "amount_usd": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "round_type": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "announced_at": {"type": "string"},
        "investors": {"type": "array", "items": {"type": "string"}},
        "raw_payload": {"type": "object"},
    },
    "required": ["source", "source_id", "announced_at"],
}

_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "is_launch": {"type": "boolean"},
        "confidence": {"type": "number"},
        "launch_type": {
            "anyOf": [
                {"type": "string", "enum": ["product", "feature", "milestone", "program"]},
                {"type": "null"},
            ]
        },
        "reasoning": {"type": "string"},
    },
    "required": ["is_launch", "confidence", "launch_type", "reasoning"],
}


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_producthunt",
            "description": (
                "Fetch recent Product Hunt posts. Returns a list of {company, launch} bundles."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 30},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["days", "limit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_mock_source",
            "description": (
                "Load a mocked source's seed items. Source mock_x and mock_linkedin return "
                "{company, launch} bundles; mock_crunchbase returns {company, funding}; "
                "mock_yc returns {company}."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": list(MOCK_SOURCES),
                    }
                },
                "required": ["source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_launch",
            "description": (
                "Classify a social post against the launch definition. Call this on PH, "
                "mock_x, and mock_linkedin items only. Do not call on Crunchbase or YC."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "post_text": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["post_text", "metadata"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persist_launch",
            "description": (
                "Upsert the company and insert the launch. Refuses items where "
                "classification.is_launch is false."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "company": _COMPANY_SCHEMA,
                    "launch": _LAUNCH_SCHEMA,
                    "classification": _CLASSIFICATION_SCHEMA,
                },
                "required": ["company", "launch", "classification"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persist_funding",
            "description": "Upsert the company and insert the funding round.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "company": _COMPANY_SCHEMA,
                    "funding": _FUNDING_SCHEMA,
                },
                "required": ["company", "funding"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persist_company",
            "description": (
                "Upsert a company with no associated launch or funding. Used for mock_yc items."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"company": _COMPANY_SCHEMA},
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "End the run. Summary is a per-source dict of counts.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "object"},
                },
                "required": ["summary"],
            },
        },
    },
]
