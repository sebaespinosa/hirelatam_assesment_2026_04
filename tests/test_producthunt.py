from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.classifier import ClassificationResult
from src.db.repo import list_companies, list_launches
from src.sources.producthunt import (
    SOURCE_NAME,
    IngestionSummary,
    ProductHuntClient,
    ingest,
    load_snapshot,
    normalize_post,
    save_snapshot,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ph_sample.json"


def _fixture_nodes() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text())["posts"]


def _launch_classifier(**_: Any) -> ClassificationResult:
    return ClassificationResult(
        is_launch=True, confidence=0.95, launch_type="product", reasoning="stub"
    )


def _reject_classifier(**_: Any) -> ClassificationResult:
    return ClassificationResult(
        is_launch=False, confidence=0.9, launch_type=None, reasoning="stub reject"
    )


# --- normalize_post --------------------------------------------------------


def test_normalize_post_full_payload() -> None:
    node = _fixture_nodes()[0]
    company, launch = normalize_post(node)

    assert company.name == "Testlaunch"
    assert company.website == "https://www.producthunt.com/posts/testlaunch"
    assert company.description == "A fake product for unit tests."

    assert launch.source == SOURCE_NAME
    assert launch.source_id == "ph-1"
    assert launch.title == "A fake product for unit tests."
    assert launch.engagement_score == 42.0
    assert launch.engagement_breakdown == {"votes": 42, "comments": 5}
    assert launch.posted_at == datetime(2026, 4, 19, 10, 0, tzinfo=UTC)

    assert launch.raw_payload["topics"] == ["Developer Tools", "Productivity"]
    assert launch.raw_payload["makers"] == [
        {"name": "Ada Lovelace", "username": "ada"},
        {"name": "Alan Turing", "username": "alan"},
    ]
    assert launch.raw_payload["media"][0] == {
        "url": "https://example.test/hero.png",
        "type": "image",
    }
    assert launch.raw_payload["raw"] == node  # un-normalized payload preserved


def test_normalize_post_minimal_payload() -> None:
    node = _fixture_nodes()[1]
    company, launch = normalize_post(node)
    assert company.name == "Minimal"
    assert launch.engagement_score == 0.0
    assert launch.raw_payload["topics"] == []
    assert launch.raw_payload["makers"] == []
    assert launch.raw_payload["media"] == []


def test_normalize_post_uses_name_when_tagline_missing() -> None:
    node = dict(_fixture_nodes()[1])
    node["tagline"] = None
    _, launch = normalize_post(node)
    assert launch.title == "Minimal"


# --- ingest (classified path) ----------------------------------------------


def test_ingest_persists_launches_and_upserts_company(db: sqlite3.Connection) -> None:
    summary = ingest(
        conn=db,
        nodes=_fixture_nodes(),
        classify_fn=_launch_classifier,
    )
    assert summary.persisted == 2
    assert summary.classified == 2
    assert summary.rejected == 0
    assert summary.errors == []

    companies = list_companies(db)
    assert {c.name for c in companies} == {"Testlaunch", "Minimal"}

    launches = list_launches(db)
    assert len(launches) == 2
    assert {launch.source_id for launch in launches} == {"ph-1", "ph-2"}
    # Classification result is persisted in raw_payload for later auditability.
    assert all("_classification" in launch.raw_payload for launch in launches)


def test_ingest_skips_rejected_posts(db: sqlite3.Connection) -> None:
    summary = ingest(
        conn=db,
        nodes=_fixture_nodes(),
        classify_fn=_reject_classifier,
    )
    assert summary.classified == 2
    assert summary.rejected == 2
    assert summary.persisted == 0
    assert list_launches(db) == []


def test_ingest_is_idempotent_on_repeat(db: sqlite3.Connection) -> None:
    ingest(conn=db, nodes=_fixture_nodes(), classify_fn=_launch_classifier)
    ingest(conn=db, nodes=_fixture_nodes(), classify_fn=_launch_classifier)
    assert len(list_launches(db)) == 2  # UNIQUE(source, source_id) dedups


def test_ingest_no_classify_persists_everything(db: sqlite3.Connection) -> None:
    def _bomb(**_: Any) -> ClassificationResult:
        raise AssertionError("classifier must not be called when classify=False")

    summary = ingest(
        conn=db,
        nodes=_fixture_nodes(),
        classify=False,
        classify_fn=_bomb,
    )
    assert summary.persisted == 2
    assert summary.classified == 0


def test_ingest_no_persist_dry_run() -> None:
    summary = ingest(
        conn=None,
        nodes=_fixture_nodes(),
        persist=False,
        classify_fn=_launch_classifier,
    )
    assert summary.classified == 2
    assert summary.persisted == 0


def test_ingest_requires_conn_when_persisting() -> None:
    with pytest.raises(ValueError):
        ingest(conn=None, nodes=[], persist=True)


def test_ingest_collects_normalize_errors(db: sqlite3.Connection) -> None:
    broken = [{"id": "bad", "name": "NoCreatedAt"}]  # missing createdAt
    summary = ingest(conn=db, nodes=broken, classify_fn=_launch_classifier)
    assert summary.errors
    assert "bad" in summary.errors[0]
    assert summary.persisted == 0


# --- snapshot round-trip ---------------------------------------------------


def test_snapshot_round_trip(tmp_path: Path) -> None:
    snapshot = tmp_path / "ph.json"
    nodes = _fixture_nodes()
    save_snapshot(nodes, path=snapshot)
    assert load_snapshot(path=snapshot) == nodes


def test_load_snapshot_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_snapshot(path=tmp_path / "absent.json")


# --- ProductHuntClient (httpx.MockTransport, no network) -------------------


def _mock_transport(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(
        transport=handler,
        base_url="https://api.producthunt.com",
        headers={"Authorization": "Bearer fake"},
    )


def test_client_paginates_until_has_next_page_false() -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["variables"])
        after = body["variables"].get("after")
        if after is None:
            page = {
                "edges": [{"cursor": "c1", "node": {"id": "ph-1"}}],
                "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
            }
        else:
            page = {
                "edges": [{"cursor": "c2", "node": {"id": "ph-2"}}],
                "pageInfo": {"hasNextPage": False, "endCursor": "c2"},
            }
        return httpx.Response(200, json={"data": {"posts": page}})

    client = ProductHuntClient(
        token="fake",
        client=_mock_transport(httpx.MockTransport(handler)),
    )
    nodes = client.fetch_posts(posted_after=datetime(2026, 4, 1, tzinfo=UTC), first=1)
    assert [n["id"] for n in nodes] == ["ph-1", "ph-2"]
    assert calls[0]["after"] is None
    assert calls[1]["after"] == "c1"


def test_client_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    # Replace sleep so the test doesn't actually wait for backoff.
    monkeypatch.setattr("src.sources.producthunt.time.sleep", lambda _: None)

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={
                "data": {
                    "posts": {
                        "edges": [{"cursor": "c", "node": {"id": "ph-after-retry"}}],
                        "pageInfo": {"hasNextPage": False, "endCursor": "c"},
                    }
                }
            },
        )

    client = ProductHuntClient(
        token="fake",
        client=_mock_transport(httpx.MockTransport(handler)),
    )
    nodes = client.fetch_posts(posted_after=datetime(2026, 4, 1, tzinfo=UTC), first=1)
    assert [n["id"] for n in nodes] == ["ph-after-retry"]
    assert attempts["n"] == 3


def test_client_surfaces_graphql_errors() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "bad query"}]})

    client = ProductHuntClient(
        token="fake",
        client=_mock_transport(httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError, match="GraphQL errors"):
        client.fetch_posts(posted_after=datetime(2026, 4, 1, tzinfo=UTC))


def test_client_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PH_DEVELOPER_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="PH_DEVELOPER_TOKEN"):
        ProductHuntClient()


def test_ingestion_summary_format() -> None:
    summary = IngestionSummary(fetched=5, classified=4, persisted=3, rejected=1)
    out = summary.format()
    assert "fetched=5" in out and "persisted=3" in out and "rejected=1" in out
