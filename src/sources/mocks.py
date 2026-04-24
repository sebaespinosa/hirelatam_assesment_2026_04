"""Loaders + ingest pipeline for the four mocked sources.

All four sources share the same entrypoint:

    ingest_mocks(conn=..., source="mock_x", classify_fn=...)

Source shape by ``source`` value:

=================== ============================ =========================
source              model(s) written             classifier?
=================== ============================ =========================
mock_x              Company + Launch             yes (X-style launch tweet)
mock_linkedin       Company + Launch             yes (LinkedIn launch post)
mock_crunchbase     Company + FundingRound       no (structured fundraise)
mock_yc             Company                      no (batch directory entry)
=================== ============================ =========================

The loader preserves the same ``IngestionSummary`` contract as the Product Hunt
source so the Phase 5 orchestrator and the dashboard report uniformly.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

from src.classifier import ClassificationResult, classify_launch
from src.db import get_connection
from src.db.repo import insert_funding, insert_launch, upsert_company
from src.models import Company, FundingRound, Launch

MOCK_X = "mock_x"
MOCK_LINKEDIN = "mock_linkedin"
MOCK_CRUNCHBASE = "mock_crunchbase"
MOCK_YC = "mock_yc"

MOCK_SOURCES = (MOCK_X, MOCK_LINKEDIN, MOCK_CRUNCHBASE, MOCK_YC)
MockSource = Literal["mock_x", "mock_linkedin", "mock_crunchbase", "mock_yc"]

SEED_DIR = Path("data/seed")

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


def load_seed(source: MockSource, *, seed_dir: Path = SEED_DIR) -> list[dict[str, Any]]:
    path = seed_dir / f"{source}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No seed at {path}. Run: python -m src.sources.mock_generator --source {source}"
        )
    return json.loads(path.read_text())


# --- normalizers -----------------------------------------------------------


def _parse_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def normalize_x(node: dict[str, Any]) -> tuple[Company, Launch]:
    company = Company(
        name=node["company_name"],
        website=node.get("company_website"),
    )
    launch = Launch(
        company_id=-1,
        source=MOCK_X,
        source_id=node["source_id"],
        title=node["post_text"],
        url=f"https://x.com/{node['handle'].lstrip('@')}",
        posted_at=_parse_dt(node["posted_at"]),
        engagement_score=float(node.get("likes", 0)),
        engagement_breakdown={
            "likes": int(node.get("likes", 0)),
            "reposts": int(node.get("reposts", 0)),
            "media": node.get("media"),
        },
        raw_payload={"handle": node.get("handle"), "raw": node},
    )
    return company, launch


def normalize_linkedin(node: dict[str, Any]) -> tuple[Company, Launch]:
    company = Company(
        name=node["company_name"],
        website=node.get("company_website"),
    )
    launch = Launch(
        company_id=-1,
        source=MOCK_LINKEDIN,
        source_id=node["source_id"],
        title=node["post_text"],
        url=node.get("company_website"),
        posted_at=_parse_dt(node["posted_at"]),
        engagement_score=float(node.get("reactions", 0)),
        engagement_breakdown={
            "reactions": int(node.get("reactions", 0)),
            "comments": int(node.get("comments", 0)),
        },
        raw_payload={"author": node.get("author"), "raw": node},
    )
    return company, launch


def normalize_crunchbase(node: dict[str, Any]) -> tuple[Company, FundingRound]:
    company = Company(
        name=node["company_name"],
        website=node.get("company_website"),
    )
    round_ = FundingRound(
        company_id=-1,
        source=MOCK_CRUNCHBASE,
        source_id=node["source_id"],
        amount_usd=int(node.get("amount_usd", 0)),
        round_type=node.get("round_type"),
        announced_at=_parse_dt(node["announced_at"]),
        investors=list(node.get("investors", [])),
        raw_payload={"raw": node},
    )
    return company, round_


def normalize_yc(node: dict[str, Any]) -> Company:
    batch = node.get("batch")
    description = node.get("description") or ""
    suffix = f" (YC {batch})" if batch else ""
    return Company(
        name=node["company_name"],
        website=node.get("company_website"),
        description=f"{description}{suffix}".strip(),
    )


# --- ingest dispatch -------------------------------------------------------


def _ingest_social(
    *,
    source: MockSource,
    conn: sqlite3.Connection | None,
    nodes: list[dict[str, Any]],
    classify: bool,
    persist: bool,
    classify_fn: ClassifyFn,
    summary: IngestionSummary,
) -> None:
    normalizer = normalize_x if source == MOCK_X else normalize_linkedin
    for node in nodes:
        try:
            company, launch = normalizer(node)
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"normalize {node.get('source_id', '?')}: {exc}")
            continue

        if classify:
            try:
                result = classify_fn(
                    post_text=launch.title,
                    metadata={
                        "source": source,
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
        assert conn is not None
        try:
            stored = upsert_company(conn, company)
            assert stored.id is not None
            launch.company_id = stored.id
            insert_launch(conn, launch)
            summary.persisted += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"persist {launch.source_id}: {exc}")


def _ingest_crunchbase(
    *,
    conn: sqlite3.Connection | None,
    nodes: list[dict[str, Any]],
    persist: bool,
    summary: IngestionSummary,
) -> None:
    for node in nodes:
        try:
            company, round_ = normalize_crunchbase(node)
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"normalize {node.get('source_id', '?')}: {exc}")
            continue

        if not persist:
            continue
        assert conn is not None
        try:
            stored = upsert_company(conn, company)
            assert stored.id is not None
            round_.company_id = stored.id
            insert_funding(conn, round_)
            summary.persisted += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"persist {round_.source_id}: {exc}")


def _ingest_yc(
    *,
    conn: sqlite3.Connection | None,
    nodes: list[dict[str, Any]],
    persist: bool,
    summary: IngestionSummary,
) -> None:
    for node in nodes:
        try:
            company = normalize_yc(node)
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"normalize {node.get('source_id', '?')}: {exc}")
            continue

        if not persist:
            continue
        assert conn is not None
        try:
            upsert_company(conn, company)
            summary.persisted += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"persist {company.name}: {exc}")


def ingest_mocks(
    *,
    conn: sqlite3.Connection | None,
    source: MockSource,
    classify: bool = True,
    persist: bool = True,
    classify_fn: ClassifyFn = classify_launch,
    nodes: list[dict[str, Any]] | None = None,
    seed_dir: Path = SEED_DIR,
) -> IngestionSummary:
    """Ingest one mocked source into the database.

    Classifier runs on social sources only (X, LinkedIn). Crunchbase and YC
    bypass it; their data is structured, not a social post.
    """
    if persist and conn is None:
        raise ValueError("conn is required when persist=True")
    if source not in MOCK_SOURCES:
        raise ValueError(f"unknown mock source: {source!r}")

    if nodes is None:
        nodes = load_seed(source, seed_dir=seed_dir)

    summary = IngestionSummary(fetched=len(nodes))
    if source in (MOCK_X, MOCK_LINKEDIN):
        _ingest_social(
            source=source,
            conn=conn,
            nodes=nodes,
            classify=classify,
            persist=persist,
            classify_fn=classify_fn,
            summary=summary,
        )
    elif source == MOCK_CRUNCHBASE:
        _ingest_crunchbase(conn=conn, nodes=nodes, persist=persist, summary=summary)
    elif source == MOCK_YC:
        _ingest_yc(conn=conn, nodes=nodes, persist=persist, summary=summary)
    return summary


# --- CLI -------------------------------------------------------------------


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=list(MOCK_SOURCES),
        default=None,
        help="Ingest one source; default ingests all four.",
    )
    parser.add_argument("--no-classify", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()

    targets = [args.source] if args.source else list(MOCK_SOURCES)

    conn: sqlite3.Connection | None = None
    if not args.no_persist:
        conn = get_connection(args.db_path)

    exit_code = 0
    try:
        for source in targets:
            try:
                summary = ingest_mocks(
                    conn=conn,
                    source=source,
                    classify=not args.no_classify,
                    persist=not args.no_persist,
                )
            except FileNotFoundError as exc:
                print(f"{source}: {exc}", file=sys.stderr)
                exit_code = 2
                continue
            print(f"{source}: {summary.format()}")
            for err in summary.errors:
                print(f"  ! {err}", file=sys.stderr)
                exit_code = max(exit_code, 1)
    finally:
        if conn is not None:
            conn.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
