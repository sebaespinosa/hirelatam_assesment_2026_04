from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.classifier import ClassificationResult
from src.db.repo import list_companies, list_funding_rounds, list_launches
from src.sources.mocks import (
    MOCK_CRUNCHBASE,
    MOCK_LINKEDIN,
    MOCK_SOURCES,
    MOCK_X,
    MOCK_YC,
    ingest_mocks,
    normalize_crunchbase,
    normalize_linkedin,
    normalize_x,
    normalize_yc,
)


def _launch_classifier(**_: Any) -> ClassificationResult:
    return ClassificationResult(
        is_launch=True, confidence=0.95, launch_type="product", reasoning="stub"
    )


def _reject_classifier(**_: Any) -> ClassificationResult:
    return ClassificationResult(
        is_launch=False, confidence=0.9, launch_type=None, reasoning="stub reject"
    )


# --- normalizers -----------------------------------------------------------


def test_normalize_x_populates_engagement_and_url() -> None:
    node = {
        "source_id": "mock_x_001",
        "handle": "@founder",
        "post_text": "Introducing Acme Rocket",
        "likes": 150,
        "reposts": 20,
        "posted_at": "2026-04-01T10:00:00Z",
        "media": "video",
        "company_name": "Acme",
        "company_website": "https://acme.example.com",
    }
    company, launch = normalize_x(node)
    assert company.name == "Acme"
    assert launch.source == MOCK_X
    assert launch.source_id == "mock_x_001"
    assert launch.engagement_score == 150.0
    assert launch.engagement_breakdown == {"likes": 150, "reposts": 20, "media": "video"}
    assert launch.url == "https://x.com/founder"
    assert launch.posted_at == datetime(2026, 4, 1, 10, 0, tzinfo=UTC)


def test_normalize_linkedin_engagement_by_reactions() -> None:
    node = {
        "source_id": "mock_li_001",
        "author": "Jane Doe",
        "post_text": "Proud to launch Acme.",
        "reactions": 300,
        "comments": 15,
        "posted_at": "2026-04-02T12:00:00Z",
        "company_name": "Acme",
        "company_website": "https://acme.example.com",
    }
    company, launch = normalize_linkedin(node)
    assert company.name == "Acme"
    assert launch.source == MOCK_LINKEDIN
    assert launch.engagement_score == 300.0
    assert launch.engagement_breakdown == {"reactions": 300, "comments": 15}


def test_normalize_crunchbase_preserves_investors() -> None:
    node = {
        "source_id": "mock_cb_001",
        "company_name": "Acme",
        "company_website": "https://acme.example.com",
        "amount_usd": 10_000_000,
        "round_type": "Series A",
        "announced_at": "2026-04-01T00:00:00Z",
        "investors": ["Foundry Labs", "Northbridge"],
    }
    company, round_ = normalize_crunchbase(node)
    assert company.name == "Acme"
    assert round_.amount_usd == 10_000_000
    assert round_.round_type == "Series A"
    assert round_.investors == ["Foundry Labs", "Northbridge"]


def test_normalize_yc_appends_batch_label() -> None:
    node = {
        "source_id": "mock_yc_001",
        "company_name": "Acme",
        "company_website": "https://acme.example.com",
        "description": "Rockets for small teams.",
        "batch": "W25",
    }
    company = normalize_yc(node)
    assert company.name == "Acme"
    assert "YC W25" in (company.description or "")


# --- ingest_mocks ----------------------------------------------------------


def _in_memory_nodes(source: str) -> list[dict[str, Any]]:
    """Small per-source fixtures; avoids depending on real seed files in tests."""
    if source == MOCK_X:
        return [
            {
                "source_id": "x_a",
                "handle": "@a",
                "post_text": "Introducing Alpha",
                "likes": 10,
                "reposts": 1,
                "posted_at": "2026-04-01T10:00:00Z",
                "media": None,
                "company_name": "Alpha",
                "company_website": "https://alpha.example.com",
            },
            {
                "source_id": "x_b",
                "handle": "@b",
                "post_text": "Now live: Beta",
                "likes": 20,
                "reposts": 3,
                "posted_at": "2026-04-02T10:00:00Z",
                "media": "video",
                "company_name": "Beta",
                "company_website": "https://beta.example.com",
            },
        ]
    if source == MOCK_LINKEDIN:
        return [
            {
                "source_id": "li_a",
                "author": "Ava",
                "post_text": "Launching Alpha today.",
                "reactions": 100,
                "comments": 5,
                "posted_at": "2026-04-01T10:00:00Z",
                "company_name": "Alpha",
                "company_website": "https://alpha.example.com",
            },
        ]
    if source == MOCK_CRUNCHBASE:
        return [
            {
                "source_id": "cb_a",
                "company_name": "Alpha",
                "company_website": "https://alpha.example.com",
                "amount_usd": 5_000_000,
                "round_type": "Seed",
                "announced_at": "2026-03-15T00:00:00Z",
                "investors": ["Foundry Labs"],
            },
        ]
    if source == MOCK_YC:
        return [
            {
                "source_id": "yc_a",
                "company_name": "Alpha",
                "company_website": "https://alpha.example.com",
                "description": "Rockets.",
                "batch": "W25",
            },
        ]
    raise AssertionError(f"unknown source {source}")


def test_ingest_mocks_x_runs_classifier_and_persists(db: sqlite3.Connection) -> None:
    summary = ingest_mocks(
        conn=db,
        source=MOCK_X,
        nodes=_in_memory_nodes(MOCK_X),
        classify_fn=_launch_classifier,
    )
    assert summary.persisted == 2
    assert summary.classified == 2
    assert summary.rejected == 0
    launches = list_launches(db, source=MOCK_X)
    assert {launch.source_id for launch in launches} == {"x_a", "x_b"}
    assert all("_classification" in launch.raw_payload for launch in launches)


def test_ingest_mocks_linkedin_rejects_routed(db: sqlite3.Connection) -> None:
    summary = ingest_mocks(
        conn=db,
        source=MOCK_LINKEDIN,
        nodes=_in_memory_nodes(MOCK_LINKEDIN),
        classify_fn=_reject_classifier,
    )
    assert summary.persisted == 0
    assert summary.rejected == 1
    assert list_launches(db, source=MOCK_LINKEDIN) == []


def test_ingest_mocks_crunchbase_skips_classifier(db: sqlite3.Connection) -> None:
    def _bomb(**_: Any) -> ClassificationResult:
        raise AssertionError("classifier must not run on crunchbase")

    summary = ingest_mocks(
        conn=db,
        source=MOCK_CRUNCHBASE,
        nodes=_in_memory_nodes(MOCK_CRUNCHBASE),
        classify_fn=_bomb,
    )
    assert summary.persisted == 1
    assert summary.classified == 0
    rounds = list_funding_rounds(db)
    assert len(rounds) == 1
    assert rounds[0].amount_usd == 5_000_000


def test_ingest_mocks_yc_creates_companies_only(db: sqlite3.Connection) -> None:
    def _bomb(**_: Any) -> ClassificationResult:
        raise AssertionError("classifier must not run on yc")

    summary = ingest_mocks(
        conn=db,
        source=MOCK_YC,
        nodes=_in_memory_nodes(MOCK_YC),
        classify_fn=_bomb,
    )
    assert summary.persisted == 1
    assert summary.classified == 0
    assert list_launches(db) == []  # no launches
    companies = list_companies(db)
    assert len(companies) == 1
    assert "YC W25" in (companies[0].description or "")


def test_ingest_mocks_unknown_source_raises() -> None:
    with pytest.raises(ValueError, match="unknown mock source"):
        ingest_mocks(conn=None, source="mock_nope", persist=False, nodes=[])


def test_ingest_mocks_requires_conn_when_persisting() -> None:
    with pytest.raises(ValueError):
        ingest_mocks(conn=None, source=MOCK_X, persist=True, nodes=[])


def test_ingest_mocks_loads_from_seed_dir(db: sqlite3.Connection, tmp_path: Path) -> None:
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "mock_x.json").write_text(json.dumps(_in_memory_nodes(MOCK_X)))
    summary = ingest_mocks(
        conn=db,
        source=MOCK_X,
        classify_fn=_launch_classifier,
        seed_dir=seed_dir,
    )
    assert summary.persisted == 2


def test_ingest_mocks_missing_seed_file_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        ingest_mocks(conn=None, source=MOCK_X, persist=False, seed_dir=empty)


def test_mock_sources_contract() -> None:
    assert set(MOCK_SOURCES) == {MOCK_X, MOCK_LINKEDIN, MOCK_CRUNCHBASE, MOCK_YC}
