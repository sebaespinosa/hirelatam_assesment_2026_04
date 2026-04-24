from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.agent.tools import (
    HANDLERS,
    TOOLS,
    ToolContext,
    handle_classify_launch,
    handle_finish,
    handle_load_mock_source,
    handle_persist_company,
    handle_persist_funding,
    handle_persist_launch,
)
from src.classifier import ClassificationResult
from src.db.repo import (
    get_company_by_name,
    list_funding_rounds,
    list_launches,
)


def _ctx(db: sqlite3.Connection | None, **overrides: Any) -> ToolContext:
    return ToolContext(conn=db, **overrides)


def _stub_classify(**_: Any) -> ClassificationResult:
    return ClassificationResult(
        is_launch=True, confidence=0.9, launch_type="product", reasoning="stub"
    )


# --- fetch / load tools ----------------------------------------------------


def test_load_mock_source_returns_bundle_shapes(
    tmp_path: Path, db: sqlite3.Connection
) -> None:
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "mock_x.json").write_text(
        json.dumps(
            [
                {
                    "source_id": "x_a",
                    "handle": "@a",
                    "post_text": "Introducing X",
                    "likes": 10,
                    "reposts": 1,
                    "posted_at": "2026-04-01T10:00:00Z",
                    "media": None,
                    "company_name": "Alpha",
                    "company_website": "https://alpha.example.com",
                }
            ]
        )
    )
    out = handle_load_mock_source({"source": "mock_x"}, _ctx(db, seed_dir=seed_dir))
    assert "items" in out
    assert len(out["items"]) == 1
    bundle = out["items"][0]
    assert set(bundle) == {"company", "launch"}
    assert bundle["company"]["name"] == "Alpha"
    assert bundle["launch"]["source"] == "mock_x"


def test_load_mock_source_crunchbase_shape(tmp_path: Path, db: sqlite3.Connection) -> None:
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "mock_crunchbase.json").write_text(
        json.dumps(
            [
                {
                    "source_id": "cb_a",
                    "company_name": "Alpha",
                    "company_website": "https://alpha.example.com",
                    "amount_usd": 5_000_000,
                    "round_type": "Seed",
                    "announced_at": "2026-03-15T00:00:00Z",
                    "investors": ["Foundry"],
                }
            ]
        )
    )
    out = handle_load_mock_source({"source": "mock_crunchbase"}, _ctx(db, seed_dir=seed_dir))
    bundle = out["items"][0]
    assert set(bundle) == {"company", "funding"}
    assert bundle["funding"]["amount_usd"] == 5_000_000


def test_load_mock_source_rejects_unknown_source(db: sqlite3.Connection) -> None:
    out = handle_load_mock_source({"source": "mock_nope"}, _ctx(db))
    assert out["code"] == "validation_error"
    assert out["items"] == []


# --- classify_launch --------------------------------------------------------


def test_classify_launch_uses_injected_fn(db: sqlite3.Connection) -> None:
    out = handle_classify_launch(
        {"post_text": "Introducing Acme", "metadata": {"source": "mock_x"}},
        _ctx(db, classify_fn=_stub_classify),
    )
    assert out["is_launch"] is True
    assert out["launch_type"] == "product"


def test_classify_launch_rejects_empty_text(db: sqlite3.Connection) -> None:
    out = handle_classify_launch({"post_text": ""}, _ctx(db))
    assert out["code"] == "validation_error"


def test_classify_launch_surfaces_classifier_errors(db: sqlite3.Connection) -> None:
    def _boom(**_: Any) -> ClassificationResult:
        raise RuntimeError("no credits")

    out = handle_classify_launch(
        {"post_text": "hi", "metadata": {}}, _ctx(db, classify_fn=_boom)
    )
    assert out["code"] == "classifier_error"
    assert "no credits" in out["error"]


# --- persist_launch --------------------------------------------------------


def _valid_launch_bundle() -> dict[str, Any]:
    return {
        "company": {"name": "Alpha", "website": "https://alpha.example.com"},
        "launch": {
            "source": "mock_x",
            "source_id": "x_a",
            "title": "Introducing Alpha",
            "url": "https://x.com/a",
            "posted_at": "2026-04-01T10:00:00Z",
            "engagement_score": 10.0,
            "engagement_breakdown": {"likes": 10, "reposts": 1},
            "raw_payload": {},
        },
        "classification": {
            "is_launch": True,
            "confidence": 0.9,
            "launch_type": "product",
            "reasoning": "stub",
        },
    }


def test_persist_launch_writes_company_and_launch(db: sqlite3.Connection) -> None:
    out = handle_persist_launch(_valid_launch_bundle(), _ctx(db))
    assert "launch_id" in out and "company_id" in out
    company = get_company_by_name(db, "Alpha")
    assert company is not None
    launches = list_launches(db, company_id=company.id)
    assert len(launches) == 1
    assert "_classification" in launches[0].raw_payload


def test_persist_launch_refuses_non_launch(db: sqlite3.Connection) -> None:
    bundle = _valid_launch_bundle()
    bundle["classification"] = {
        "is_launch": False,
        "confidence": 0.9,
        "launch_type": None,
        "reasoning": "teaser",
    }
    out = handle_persist_launch(bundle, _ctx(db))
    assert out["code"] == "policy_error"
    assert get_company_by_name(db, "Alpha") is None


def test_persist_launch_validation_error_returns_structured(db: sqlite3.Connection) -> None:
    bundle = _valid_launch_bundle()
    bundle["launch"].pop("posted_at")  # required
    out = handle_persist_launch(bundle, _ctx(db))
    assert out["code"] == "validation_error"
    assert out["model"] == "Launch"


def test_persist_launch_dry_run_skips_db(db: sqlite3.Connection) -> None:
    out = handle_persist_launch(_valid_launch_bundle(), _ctx(db, persist=False))
    assert out.get("dry_run") is True
    assert get_company_by_name(db, "Alpha") is None


# --- persist_funding -------------------------------------------------------


def _valid_funding_bundle() -> dict[str, Any]:
    return {
        "company": {"name": "Alpha"},
        "funding": {
            "source": "mock_crunchbase",
            "source_id": "cb_a",
            "amount_usd": 10_000_000,
            "round_type": "Series A",
            "announced_at": "2026-03-15T00:00:00Z",
            "investors": ["Foundry"],
            "raw_payload": {},
        },
    }


def test_persist_funding_happy_path(db: sqlite3.Connection) -> None:
    out = handle_persist_funding(_valid_funding_bundle(), _ctx(db))
    assert "funding_id" in out
    rounds = list_funding_rounds(db)
    assert rounds[0].amount_usd == 10_000_000


def test_persist_funding_validation_error(db: sqlite3.Connection) -> None:
    bundle = _valid_funding_bundle()
    bundle["funding"].pop("announced_at")
    out = handle_persist_funding(bundle, _ctx(db))
    assert out["code"] == "validation_error"


# --- persist_company -------------------------------------------------------


def test_persist_company_happy_path(db: sqlite3.Connection) -> None:
    out = handle_persist_company({"company": {"name": "Alpha"}}, _ctx(db))
    assert "company_id" in out
    assert get_company_by_name(db, "Alpha") is not None


def test_persist_company_validation_error(db: sqlite3.Connection) -> None:
    out = handle_persist_company({"company": {}}, _ctx(db))  # missing name
    assert out["code"] == "validation_error"


# --- finish + dispatch -----------------------------------------------------


def test_finish_sets_context_flag() -> None:
    ctx = ToolContext(conn=None, persist=False)
    out = handle_finish({"summary": {"by_source": {}}}, ctx)
    assert out["ok"] is True
    assert ctx.finished is True
    assert ctx.finish_summary == {"by_source": {}}


def test_finish_rejects_non_dict_summary() -> None:
    ctx = ToolContext(conn=None, persist=False)
    out = handle_finish({"summary": "not a dict"}, ctx)
    assert out["code"] == "validation_error"
    assert ctx.finished is False


def test_handlers_cover_every_tool() -> None:
    assert set(HANDLERS) == {tool["function"]["name"] for tool in TOOLS}


def test_tool_schemas_have_strict_additional_properties() -> None:
    for tool in TOOLS:
        schema = tool["function"]["parameters"]
        assert schema.get("additionalProperties") is False, tool["function"]["name"]
