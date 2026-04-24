"""Product Hunt ingestion.

Pulls recent posts from the Product Hunt GraphQL API, routes each one
through the Phase 2 launch classifier, and persists the launches to SQLite.

Offline behavior
----------------
On any network failure the CLI falls back to ``data/seed/ph_snapshot.json``.
A successful live fetch overwrites that snapshot so a subsequent offline run
replays the last known good response. The snapshot is gitignored; an
assessment reviewer regenerates it by registering a PH developer app and
running the CLI once.

Usage
-----
    python -m src.sources.producthunt                  # live fetch + classify + persist
    python -m src.sources.producthunt --days 14        # wider lookback window
    python -m src.sources.producthunt --from-snapshot  # skip network, use cached payload
    python -m src.sources.producthunt --no-classify    # persist everything (dev only)
    python -m src.sources.producthunt --no-persist     # dry run — print summary only

PH GraphQL schema reference: https://api.producthunt.com/v2/docs
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from src.classifier import ClassificationResult, classify_launch
from src.db import get_connection
from src.db.repo import insert_launch, upsert_company
from src.models import Company, Launch

SOURCE_NAME = "producthunt"
GRAPHQL_ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
SNAPSHOT_PATH = Path("data/seed/ph_snapshot.json")

POSTS_QUERY = """
query RecentPosts($postedAfter: DateTime!, $first: Int!, $after: String) {
  posts(first: $first, after: $after, postedAfter: $postedAfter, order: VOTES) {
    edges {
      cursor
      node {
        id
        name
        slug
        tagline
        url
        votesCount
        commentsCount
        createdAt
        topics(first: 5) {
          edges { node { name } }
        }
        makers {
          id
          name
          username
        }
        media {
          url
          type
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
""".strip()


# --- client ----------------------------------------------------------------


class ProductHuntClient:
    """Thin GraphQL client. Paginates and retries on 429; everything else surfaces."""

    def __init__(
        self,
        token: str | None = None,
        *,
        endpoint: str = GRAPHQL_ENDPOINT,
        client: httpx.Client | None = None,
    ) -> None:
        self.token = token or os.environ.get("PH_DEVELOPER_TOKEN")
        if not self.token:
            raise RuntimeError(
                "PH_DEVELOPER_TOKEN not set. Register an app at "
                "https://api.producthunt.com/v2/oauth/applications and put the "
                "developer token in .env."
            )
        self.endpoint = endpoint
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(30.0),
            headers={
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "hirelatam-assessment/0.1",
                "Accept": "application/json",
            },
        )

    def __enter__(self) -> ProductHuntClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def fetch_posts(
        self,
        *,
        posted_after: datetime,
        first: int = 20,
        max_pages: int = 5,
    ) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(max_pages):
            data = self._query(
                POSTS_QUERY,
                variables={
                    "postedAfter": posted_after.isoformat(),
                    "first": first,
                    "after": after,
                },
            )
            page = data["posts"]
            nodes.extend(edge["node"] for edge in page["edges"])
            page_info = page.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
        return nodes

    def _query(self, query: str, *, variables: dict[str, Any]) -> dict[str, Any]:
        body = {"query": query, "variables": variables}
        for attempt in range(4):
            response = self._client.post(self.endpoint, json=body)
            if response.status_code == 429:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(f"GraphQL errors: {payload['errors']}")
            return payload["data"]
        raise RuntimeError("Exceeded retry budget on 429s.")


# --- normalization ---------------------------------------------------------


def normalize_post(node: dict[str, Any]) -> tuple[Company, Launch]:
    """Map a PH post node to a ``(Company, Launch)`` pair.

    The returned ``Launch.company_id`` is a placeholder (-1); the caller
    upserts the company first and fills in the real id before
    ``insert_launch``. ``raw_payload`` preserves the full un-normalized node
    so the debugging story survives schema drift.
    """
    name = node["name"]
    topics = [edge["node"]["name"] for edge in (node.get("topics") or {}).get("edges", [])]
    makers = [
        {"name": m.get("name"), "username": m.get("username")}
        for m in (node.get("makers") or [])
    ]
    media = [
        {"url": m.get("url"), "type": m.get("type")}
        for m in (node.get("media") or [])
    ]

    company = Company(
        name=name,
        website=node.get("url"),
        description=node.get("tagline"),
    )
    launch = Launch(
        company_id=-1,
        source=SOURCE_NAME,
        source_id=str(node["id"]),
        title=node.get("tagline") or name,
        url=node.get("url"),
        posted_at=_parse_datetime(node["createdAt"]),
        engagement_score=float(node.get("votesCount") or 0),
        engagement_breakdown={
            "votes": int(node.get("votesCount") or 0),
            "comments": int(node.get("commentsCount") or 0),
        },
        raw_payload={
            "name": name,
            "slug": node.get("slug"),
            "topics": topics,
            "makers": makers,
            "media": media,
            "raw": node,
        },
    )
    return company, launch


def _parse_datetime(value: str) -> datetime:
    # Product Hunt emits RFC3339 with a trailing Z; fromisoformat needs +00:00 on older Pythons.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# --- snapshot fallback -----------------------------------------------------


def save_snapshot(nodes: list[dict[str, Any]], path: Path = SNAPSHOT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"captured_at": datetime.now(UTC).isoformat(), "posts": nodes}
    path.write_text(json.dumps(payload, indent=2))


def load_snapshot(path: Path = SNAPSHOT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"No snapshot at {path}. Run the CLI once with PH_DEVELOPER_TOKEN set "
            "to capture one, or point --db-path at a separately-seeded database."
        )
    return json.loads(path.read_text())["posts"]


# --- pipeline --------------------------------------------------------------


ClassifyFn = Callable[..., ClassificationResult]


@dataclass
class IngestionSummary:
    fetched: int = 0
    classified: int = 0
    persisted: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)

    def format(self) -> str:
        return (
            f"fetched={self.fetched} classified={self.classified} "
            f"persisted={self.persisted} rejected={self.rejected} "
            f"errors={len(self.errors)}"
        )


def ingest(
    *,
    conn: sqlite3.Connection | None,
    nodes: list[dict[str, Any]],
    classify: bool = True,
    persist: bool = True,
    classify_fn: ClassifyFn = classify_launch,
) -> IngestionSummary:
    """Route fetched PH posts through classify + persist.

    ``conn`` may be ``None`` iff ``persist=False`` (dry-run mode). ``classify_fn``
    is a parameter so tests can inject a deterministic fake without touching
    the OpenAI client.
    """
    if persist and conn is None:
        raise ValueError("conn is required when persist=True")

    summary = IngestionSummary()
    summary.fetched = len(nodes)

    for node in nodes:
        try:
            company, launch = normalize_post(node)
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"normalize {node.get('id', '?')}: {exc}")
            continue

        if classify:
            try:
                result = classify_fn(
                    post_text=launch.title,
                    metadata={
                        "source": SOURCE_NAME,
                        "url": launch.url,
                        "engagement": launch.engagement_breakdown,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                summary.errors.append(f"classify {launch.source_id}: {exc}")
                continue
            summary.classified += 1
            launch.raw_payload["_classification"] = result.model_dump()
            if not result.is_launch:
                summary.rejected += 1
                continue

        if not persist:
            continue

        assert conn is not None  # guarded above
        try:
            stored_company = upsert_company(conn, company)
            assert stored_company.id is not None
            launch.company_id = stored_company.id
            insert_launch(conn, launch)
            summary.persisted += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"persist {launch.source_id}: {exc}")

    return summary


# --- CLI -------------------------------------------------------------------


def _fetch_nodes(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.from_snapshot:
        return load_snapshot()
    try:
        with ProductHuntClient() as client:
            posted_after = datetime.now(UTC) - timedelta(days=args.days)
            nodes = client.fetch_posts(
                posted_after=posted_after,
                first=args.first,
                max_pages=args.max_pages,
            )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Live fetch failed ({type(exc).__name__}: {exc}); "
            f"falling back to snapshot.",
            file=sys.stderr,
        )
        return load_snapshot()
    save_snapshot(nodes)
    return nodes


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days.")
    parser.add_argument("--first", type=int, default=20, help="Posts per GraphQL page.")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument(
        "--from-snapshot",
        action="store_true",
        help="Skip network; use data/seed/ph_snapshot.json.",
    )
    parser.add_argument(
        "--no-classify",
        action="store_true",
        help="Persist all fetched posts without calling the launch classifier.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Dry run — classify but do not write to SQLite.",
    )
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()

    try:
        nodes = _fetch_nodes(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    conn: sqlite3.Connection | None = None
    if not args.no_persist:
        conn = get_connection(args.db_path)
    try:
        summary = ingest(
            conn=conn,
            nodes=nodes,
            classify=not args.no_classify,
            persist=not args.no_persist,
        )
    finally:
        if conn is not None:
            conn.close()

    print(summary.format())
    for err in summary.errors:
        print(f"  ! {err}", file=sys.stderr)
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    sys.exit(main())
