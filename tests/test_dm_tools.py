from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from src.agent.dm_tools import (
    DM_HANDLERS,
    DM_TOOLS,
    handle_finish,
    handle_list_underperforming_launches,
    handle_persist_dm_draft,
    load_dm_prompt_version,
    load_dm_system_prompt,
)
from src.agent.thresholds import list_underperforming_launches, percentile
from src.agent.tools import ToolContext
from src.db.repo import (
    insert_contact,
    insert_launch,
    list_dm_drafts_by_launch,
    upsert_company,
)
from src.models import Company, Contact, Launch


def _ctx(db: sqlite3.Connection | None, **overrides: Any) -> ToolContext:
    return ToolContext(conn=db, **overrides)


def _seed_launches(
    db: sqlite3.Connection,
    source: str,
    scores: list[float],
    *,
    posted_days_ago: int = 10,
) -> list[Launch]:
    company = upsert_company(db, Company(name=f"{source}-co"))
    assert company.id is not None
    posted_at = datetime.now(UTC) - timedelta(days=posted_days_ago)
    out = []
    for i, score in enumerate(scores):
        launch = insert_launch(
            db,
            Launch(
                company_id=company.id,
                source=source,
                source_id=f"{source}-{i}",
                title=f"{source}-launch-{i}",
                posted_at=posted_at,
                engagement_score=score,
            ),
        )
        out.append(launch)
    return out


# --- percentile ------------------------------------------------------------


def test_percentile_basic() -> None:
    assert percentile([1, 2, 3, 4], 25) == 1.75
    assert percentile([10, 20, 30, 40], 50) == 25.0
    assert percentile([], 50) == 0.0
    assert percentile([5], 50) == 5


def test_percentile_respects_pct_bounds() -> None:
    values = list(range(100))
    p25 = percentile(values, 25)
    p75 = percentile(values, 75)
    assert p25 < p75
    assert 0 <= p25 <= 99
    assert 0 <= p75 <= 99


# --- list_underperforming_launches ----------------------------------------


def test_threshold_groups_by_source(db: sqlite3.Connection) -> None:
    # PH and mock_x have different engagement shapes; the bottom-quartile
    # launches must be picked out per-source, not globally.
    _seed_launches(db, "producthunt", [10, 20, 30, 40, 50, 60, 70, 80])
    _seed_launches(db, "mock_x", [100, 200, 300, 400, 500, 600, 700, 800])

    results = list_underperforming_launches(db)
    sources = {r["source"] for r in results}
    assert sources == {"producthunt", "mock_x"}


def test_threshold_excludes_above_p25(db: sqlite3.Connection) -> None:
    _seed_launches(db, "mock_x", [1, 2, 3, 4, 5, 6, 7, 8])
    results = list_underperforming_launches(db)
    returned_scores = [r["engagement_score"] for r in results]
    # P25 of 1..8 is 2.75 (linear interp). So 1 and 2 are < 2.75.
    assert set(returned_scores) == {1, 2}


def test_threshold_respects_window_days(db: sqlite3.Connection) -> None:
    _seed_launches(db, "mock_x", [1, 2, 3, 4, 5, 6, 7, 8], posted_days_ago=180)
    results = list_underperforming_launches(db, window_days=30)
    assert results == []


def test_threshold_caps_max_count(db: sqlite3.Connection) -> None:
    # 100 low-engagement launches; only the lowest max_count should return.
    _seed_launches(db, "mock_x", list(range(100)))
    results = list_underperforming_launches(db, max_count=3)
    assert len(results) == 3
    # sorted ascending by engagement_score
    assert results[0]["engagement_score"] <= results[-1]["engagement_score"]


def test_threshold_includes_contact_context(db: sqlite3.Connection) -> None:
    _seed_launches(db, "mock_x", [1, 2, 3, 4])
    company = upsert_company(db, Company(name="mock_x-co"))
    assert company.id is not None
    insert_contact(
        db,
        Contact(company_id=company.id, email="ceo@co.test", confidence=0.9, source="mock"),
    )
    results = list_underperforming_launches(db)
    # P25 of [1,2,3,4] = 1.75 → only 1 qualifies
    assert len(results) == 1
    assert results[0]["contact"]["email"] == "ceo@co.test"


# --- prompt loader ---------------------------------------------------------


def test_dm_system_prompt_strips_header() -> None:
    prompt = load_dm_system_prompt()
    assert "You write short outbound DMs" in prompt
    assert "**Version:**" not in prompt
    assert "# DM Draft" not in prompt


def test_dm_prompt_version() -> None:
    assert load_dm_prompt_version() == "v1"


# --- handle_list_underperforming_launches ---------------------------------


def test_handle_list_returns_launches_bundle(db: sqlite3.Connection) -> None:
    _seed_launches(db, "mock_x", [1, 2, 3, 4, 5, 6, 7, 8])
    out = handle_list_underperforming_launches({}, _ctx(db))
    assert "launches" in out
    assert all("launch_id" in launch for launch in out["launches"])


def test_handle_list_no_conn_returns_error() -> None:
    out = handle_list_underperforming_launches({}, _ctx(None))
    assert out["code"] == "runtime_error"


# --- handle_persist_dm_draft -----------------------------------------------


def test_persist_dm_draft_happy_path(db: sqlite3.Connection) -> None:
    launches = _seed_launches(db, "mock_x", [1])
    launch = launches[0]
    assert launch.id is not None

    out = handle_persist_dm_draft(
        {
            "launch_id": launch.id,
            "subject": "Loved the launch",
            "body": "Hey — saw your mock_x-launch-0 go out. ...",
            "tone": "warm",
        },
        _ctx(db),
    )
    assert "dm_draft_id" in out
    drafts = list_dm_drafts_by_launch(db, launch.id)
    assert len(drafts) == 1
    assert drafts[0].prompt_version == "v1"  # auto-injected


def test_persist_dm_draft_validation_error_missing_body(db: sqlite3.Connection) -> None:
    launches = _seed_launches(db, "mock_x", [1])
    assert launches[0].id is not None
    out = handle_persist_dm_draft(
        {"launch_id": launches[0].id, "subject": "x", "tone": "warm"},  # body missing
        _ctx(db),
    )
    assert out["code"] == "validation_error"


def test_persist_dm_draft_dry_run(db: sqlite3.Connection) -> None:
    launches = _seed_launches(db, "mock_x", [1])
    assert launches[0].id is not None
    out = handle_persist_dm_draft(
        {
            "launch_id": launches[0].id,
            "subject": "x",
            "body": "y",
            "tone": "warm",
        },
        _ctx(db, persist=False),
    )
    assert out.get("dry_run") is True
    assert list_dm_drafts_by_launch(db, launches[0].id) == []


# --- finish + dispatch ----------------------------------------------------


def test_handle_finish_sets_ctx() -> None:
    ctx = ToolContext(conn=None, persist=False)
    out = handle_finish({"summary": {"drafts_persisted": 5}}, ctx)
    assert out["ok"] is True
    assert ctx.finished is True


def test_dm_handlers_cover_every_tool() -> None:
    assert set(DM_HANDLERS) == {tool["function"]["name"] for tool in DM_TOOLS}


def test_dm_tool_schemas_are_strict() -> None:
    for tool in DM_TOOLS:
        schema = tool["function"]["parameters"]
        assert schema.get("additionalProperties") is False, tool["function"]["name"]
