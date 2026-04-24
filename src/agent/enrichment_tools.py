"""Tool definitions + handlers for the Phase 6 enrichment pass.

The four ``find_*`` tools are mocked — they synthesize plausible-looking
contact info deterministically seeded by ``company_name`` so re-runs are
idempotent and tests can assert exact output. Production swap would route
each tool to a vendor (Hunter.io for email, Apollo.io for phones + LinkedIn,
an X API proxy for handles).

Shares ``ToolContext`` and error conventions with the Phase 5 ingestion
tools — Pydantic validation errors return ``{"error": ..., "code":
"validation_error"}`` so the agent can self-correct.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.agent.tools import ToolContext
from src.db.repo import insert_contact, list_companies_without_contacts
from src.models import Contact

ENRICHMENT_PROMPT_PATH = Path("prompts/enrichment.md")
_PROMPT_MARKER = "## System Prompt"
_VERSION_RE = re.compile(r"\*\*Version:\*\*\s*(\S+)")

MISS_RATE_EMAIL = 0.15
MISS_RATE_PHONE = 0.30
MISS_RATE_LINKEDIN = 0.05
MISS_RATE_X = 0.20

_EMAIL_PREFIXES = ["ceo", "founder", "hello", "contact", "press", "hi"]
_PHONE_AREA_CODES = ["415", "212", "310", "206", "617", "512"]


def load_enrichment_system_prompt() -> str:
    content = ENRICHMENT_PROMPT_PATH.read_text()
    idx = content.find(_PROMPT_MARKER)
    return content[idx + len(_PROMPT_MARKER) :].strip() if idx != -1 else content.strip()


def load_enrichment_prompt_version() -> str:
    content = ENRICHMENT_PROMPT_PATH.read_text()
    match = _VERSION_RE.search(content)
    return match.group(1) if match else "unknown"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _rng(company_name: str, field: str) -> random.Random:
    """Deterministic RNG — same company + field => same output across runs."""
    seed = int(hashlib.md5(f"{company_name}:{field}".encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _maybe_miss(rng: random.Random, miss_rate: float) -> bool:
    return rng.random() < miss_rate


# --- handlers --------------------------------------------------------------


def handle_list_companies_missing_contacts(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    if ctx.conn is None:
        return {"error": "no database connection", "code": "runtime_error", "companies": []}
    companies = list_companies_without_contacts(ctx.conn)
    return {
        "companies": [
            {"id": c.id, "name": c.name, "website": c.website} for c in companies
        ]
    }


def handle_find_email(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = args.get("company_name")
    if not isinstance(name, str) or not name.strip():
        return {"error": "company_name required", "code": "validation_error"}
    rng = _rng(name, "email")
    if _maybe_miss(rng, MISS_RATE_EMAIL):
        return {"email": None, "confidence": 0.0, "source": "mock"}
    prefix = rng.choice(_EMAIL_PREFIXES)
    slug = _slug(name) or "company"
    return {
        "email": f"{prefix}@{slug}.com",
        "confidence": round(rng.uniform(0.55, 0.95), 2),
        "source": "mock",
    }


def handle_find_phone(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = args.get("company_name")
    if not isinstance(name, str) or not name.strip():
        return {"error": "company_name required", "code": "validation_error"}
    rng = _rng(name, "phone")
    if _maybe_miss(rng, MISS_RATE_PHONE):
        return {"phone": None, "confidence": 0.0, "source": "mock"}
    area = rng.choice(_PHONE_AREA_CODES)
    mid = rng.randint(200, 999)
    tail = rng.randint(1000, 9999)
    return {
        "phone": f"+1-{area}-{mid}-{tail}",
        "confidence": round(rng.uniform(0.40, 0.80), 2),
        "source": "mock",
    }


def handle_find_linkedin(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = args.get("company_name")
    if not isinstance(name, str) or not name.strip():
        return {"error": "company_name required", "code": "validation_error"}
    rng = _rng(name, "linkedin")
    if _maybe_miss(rng, MISS_RATE_LINKEDIN):
        return {"linkedin_url": None, "confidence": 0.0, "source": "mock"}
    slug = _slug(name) or "company"
    return {
        "linkedin_url": f"https://linkedin.com/company/{slug}",
        "confidence": round(rng.uniform(0.70, 0.98), 2),
        "source": "mock",
    }


def handle_find_x_handle(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = args.get("company_name")
    if not isinstance(name, str) or not name.strip():
        return {"error": "company_name required", "code": "validation_error"}
    rng = _rng(name, "x")
    if _maybe_miss(rng, MISS_RATE_X):
        return {"x_handle": None, "confidence": 0.0, "source": "mock"}
    slug = (_slug(name) or "company")[:15]  # X handle limit
    return {
        "x_handle": f"@{slug}",
        "confidence": round(rng.uniform(0.50, 0.90), 2),
        "source": "mock",
    }


def handle_persist_contact(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    data = {
        "company_id": args.get("company_id"),
        "email": args.get("email"),
        "phone": args.get("phone"),
        "linkedin_url": args.get("linkedin_url"),
        "x_handle": args.get("x_handle"),
        "confidence": args.get("confidence", 0.0),
        "source": args.get("source", "mock"),
    }
    try:
        contact = Contact.model_validate(data)
    except ValidationError as exc:
        return {"error": str(exc), "code": "validation_error", "model": "Contact"}

    if not ctx.persist or ctx.conn is None:
        return {"dry_run": True, "company_id": contact.company_id}

    stored = insert_contact(ctx.conn, contact)
    return {"contact_id": stored.id, "company_id": contact.company_id}


def handle_finish(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    summary = args.get("summary")
    if not isinstance(summary, dict):
        return {"error": "summary must be an object", "code": "validation_error"}
    ctx.finished = True
    ctx.finish_summary = summary
    return {"ok": True}


ENRICHMENT_HANDLERS: dict[str, Callable[[dict[str, Any], ToolContext], dict[str, Any]]] = {
    "list_companies_missing_contacts": handle_list_companies_missing_contacts,
    "find_email": handle_find_email,
    "find_phone": handle_find_phone,
    "find_linkedin": handle_find_linkedin,
    "find_x_handle": handle_find_x_handle,
    "persist_contact": handle_persist_contact,
    "finish": handle_finish,
}


# --- OpenAI tool definitions -----------------------------------------------


_COMPANY_REF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "company_id": {"type": "integer"},
        "company_name": {"type": "string"},
    },
    "required": ["company_id", "company_name"],
}


ENRICHMENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_companies_missing_contacts",
            "description": (
                "Return companies that do not yet have a contact row. Call this first."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_email",
            "description": (
                "Look up an email address for a company. Returns {email, confidence, source}."
            ),
            "parameters": _COMPANY_REF_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_phone",
            "description": "Look up a phone number for a company.",
            "parameters": _COMPANY_REF_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_linkedin",
            "description": "Look up a LinkedIn company URL.",
            "parameters": _COMPANY_REF_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_x_handle",
            "description": "Look up an X (Twitter) handle.",
            "parameters": _COMPANY_REF_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persist_contact",
            "description": "Write exactly one contact row for a company.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "company_id": {"type": "integer"},
                    "email": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "phone": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "linkedin_url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "x_handle": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "confidence": {"type": "number"},
                    "source": {"type": "string"},
                },
                "required": ["company_id", "confidence", "source"],
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
