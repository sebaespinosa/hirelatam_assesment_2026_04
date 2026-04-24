"""One-shot generator for the mocked source seed JSON.

Produces four files under ``data/seed/``:

* ``mock_x.json`` — 20 X-style launch posts
* ``mock_linkedin.json`` — 15 LinkedIn-style launch posts
* ``mock_crunchbase.json`` — 30 fundraise records
* ``mock_yc.json`` — 15 YC batch companies

Run once and commit the output. Regenerate when the schema or classifier
definition changes in a way that makes the existing seeds look wrong.

Usage:
    python -m src.sources.mock_generator                  # regenerate all four
    python -m src.sources.mock_generator --source mock_x  # regenerate one
    python -m src.sources.mock_generator --dry-run        # print prompts, no API call
    python -m src.sources.mock_generator --model gpt-4o   # bigger model for quality
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

SEED_DIR = Path("data/seed")
PROMPT_PATH = Path("prompts/mock_generator.md")
DEFAULT_MODEL = "gpt-4o-mini"

MOCK_X = "mock_x"
MOCK_LINKEDIN = "mock_linkedin"
MOCK_CRUNCHBASE = "mock_crunchbase"
MOCK_YC = "mock_yc"

MOCK_SOURCES = [MOCK_X, MOCK_LINKEDIN, MOCK_CRUNCHBASE, MOCK_YC]

COUNTS: dict[str, int] = {
    MOCK_X: 20,
    MOCK_LINKEDIN: 15,
    MOCK_CRUNCHBASE: 30,
    MOCK_YC: 15,
}


def _schema(source: str, item_properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Wrap per-item schema in the Structured Outputs-required envelope."""
    return {
        "name": source,
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": item_properties,
                        "required": required,
                    },
                },
            },
            "required": ["items"],
        },
    }


SCHEMAS: dict[str, dict[str, Any]] = {
    MOCK_X: _schema(
        MOCK_X,
        {
            "source_id": {"type": "string"},
            "handle": {"type": "string"},
            "post_text": {"type": "string"},
            "likes": {"type": "integer"},
            "reposts": {"type": "integer"},
            "posted_at": {"type": "string"},
            "media": {
                "anyOf": [
                    {"type": "string", "enum": ["video", "screenshot", "image", "link"]},
                    {"type": "null"},
                ]
            },
            "company_name": {"type": "string"},
            "company_website": {"type": "string"},
        },
        [
            "source_id",
            "handle",
            "post_text",
            "likes",
            "reposts",
            "posted_at",
            "media",
            "company_name",
            "company_website",
        ],
    ),
    MOCK_LINKEDIN: _schema(
        MOCK_LINKEDIN,
        {
            "source_id": {"type": "string"},
            "author": {"type": "string"},
            "post_text": {"type": "string"},
            "reactions": {"type": "integer"},
            "comments": {"type": "integer"},
            "posted_at": {"type": "string"},
            "company_name": {"type": "string"},
            "company_website": {"type": "string"},
        },
        [
            "source_id",
            "author",
            "post_text",
            "reactions",
            "comments",
            "posted_at",
            "company_name",
            "company_website",
        ],
    ),
    MOCK_CRUNCHBASE: _schema(
        MOCK_CRUNCHBASE,
        {
            "source_id": {"type": "string"},
            "company_name": {"type": "string"},
            "company_website": {"type": "string"},
            "amount_usd": {"type": "integer"},
            "round_type": {
                "type": "string",
                "enum": [
                    "Pre-seed",
                    "Seed",
                    "Series A",
                    "Series B",
                    "Series C",
                    "Series D",
                ],
            },
            "announced_at": {"type": "string"},
            "investors": {"type": "array", "items": {"type": "string"}},
        },
        [
            "source_id",
            "company_name",
            "company_website",
            "amount_usd",
            "round_type",
            "announced_at",
            "investors",
        ],
    ),
    MOCK_YC: _schema(
        MOCK_YC,
        {
            "source_id": {"type": "string"},
            "company_name": {"type": "string"},
            "company_website": {"type": "string"},
            "description": {"type": "string"},
            "batch": {
                "type": "string",
                "enum": ["S24", "W24", "X25", "S25", "F25", "W25"],
            },
        },
        ["source_id", "company_name", "company_website", "description", "batch"],
    ),
}

USER_MESSAGES: dict[str, str] = {
    MOCK_X: (
        "Generate {n} X (Twitter) launch posts. Each item: source_id, handle, "
        "post_text (140–280 chars), likes, reposts, posted_at (ISO 8601 UTC), "
        "media (video/screenshot/image/link or null), company_name, "
        "company_website."
    ),
    MOCK_LINKEDIN: (
        "Generate {n} LinkedIn launch posts. Each item: source_id, author (full "
        "name), post_text (200–500 chars, slightly more formal than X), reactions, "
        "comments, posted_at (ISO 8601 UTC), company_name, company_website."
    ),
    MOCK_CRUNCHBASE: (
        "Generate {n} Crunchbase-style fundraise records. Each item: source_id, "
        "company_name, company_website, amount_usd, round_type "
        "(Pre-seed/Seed/Series A/Series B/Series C/Series D), announced_at (ISO "
        "8601 UTC), investors (array of 2–5 plausibly-invented firm names)."
    ),
    MOCK_YC: (
        "Generate {n} YC batch companies. Each item: source_id, company_name, "
        "company_website, description (1–2 sentence product pitch), batch "
        "(S24/W24/X25/S25/F25/W25)."
    ),
}


def load_system_prompt() -> str:
    content = PROMPT_PATH.read_text()
    marker = "## System Prompt"
    idx = content.find(marker)
    return content[idx + len(marker) :].strip() if idx != -1 else content.strip()


def user_message(source: str) -> str:
    return USER_MESSAGES[source].format(n=COUNTS[source])


def generate_source(source: str, *, client: Any, model: str) -> list[dict[str, Any]]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": load_system_prompt()},
            {"role": "user", "content": user_message(source)},
        ],
        response_format={"type": "json_schema", "json_schema": SCHEMAS[source]},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(f"Empty response for {source}")
    return json.loads(content)["items"]


def write_seed(source: str, items: list[dict[str, Any]]) -> Path:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    path = SEED_DIR / f"{source}.json"
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n")
    return path


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=MOCK_SOURCES,
        default=None,
        help="Regenerate one source.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts and schemas; no API call.",
    )
    args = parser.parse_args()

    targets = [args.source] if args.source else MOCK_SOURCES

    if args.dry_run:
        for source in targets:
            print(f"--- {source} (n={COUNTS[source]}) ---")
            print("user message:", user_message(source))
            print("schema.name:", SCHEMAS[source]["name"])
        return 0

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set — put it in .env.", file=sys.stderr)
        return 2

    from openai import OpenAI

    client = OpenAI()
    for source in targets:
        print(f"generating {source} (n={COUNTS[source]}, model={args.model})...", file=sys.stderr)
        items = generate_source(source, client=client, model=args.model)
        path = write_seed(source, items)
        print(f"  wrote {len(items)} items to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
