from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.dashboard.queries import (
    ALL_SOURCES,
    get_company_detail,
    get_kpis,
    get_top_raised,
    list_dashboard_rows,
)
from src.db.repo import (
    insert_contact,
    insert_dm_draft,
    insert_funding,
    insert_launch,
    upsert_company,
)
from src.models import Company, Contact, DmDraft, FundingRound, Launch


def _seed_full_graph(db: sqlite3.Connection) -> dict[str, int]:
    """Seed a small graph across all 5 sources and every table. Return id handles."""
    alpha = upsert_company(db, Company(name="Alpha", website="https://alpha.example.com"))
    bravo = upsert_company(db, Company(name="Bravo"))
    charlie = upsert_company(db, Company(name="Charlie"))
    assert alpha.id and bravo.id and charlie.id

    now = datetime.now(UTC)
    # Alpha: real PH launch + mock_x launch + Crunchbase round + contact + DM draft
    ph_launch = insert_launch(
        db,
        Launch(
            company_id=alpha.id,
            source="producthunt",
            source_id="ph-a",
            title="Alpha launches Alpha",
            posted_at=now - timedelta(days=1),
            engagement_score=100.0,
        ),
    )
    insert_launch(
        db,
        Launch(
            company_id=alpha.id,
            source="mock_x",
            source_id="x-a",
            title="Mock post for Alpha",
            posted_at=now - timedelta(days=2),
            engagement_score=40.0,
        ),
    )
    insert_funding(
        db,
        FundingRound(
            company_id=alpha.id,
            source="mock_crunchbase",
            source_id="cb-a",
            amount_usd=10_000_000,
            round_type="Series A",
            announced_at=now - timedelta(days=5),
            investors=["Foundry"],
        ),
    )
    insert_contact(
        db,
        Contact(company_id=alpha.id, email="ceo@alpha.com", confidence=0.9, source="mock"),
    )
    assert ph_launch.id is not None
    insert_dm_draft(
        db,
        DmDraft(
            launch_id=ph_launch.id,
            subject="re: Alpha",
            body="Hi — saw your Alpha launch…",
            tone="warm",
            prompt_version="v1",
        ),
    )

    # Bravo: YC only (company-only, no launch, no funding)
    # Nothing to insert here beyond the company; simulates a YC directory entry.

    # Charlie: producthunt only, with a smaller round
    insert_launch(
        db,
        Launch(
            company_id=charlie.id,
            source="producthunt",
            source_id="ph-c",
            title="Charlie launches",
            posted_at=now - timedelta(days=10),
            engagement_score=20.0,
        ),
    )
    insert_funding(
        db,
        FundingRound(
            company_id=charlie.id,
            source="mock_crunchbase",
            source_id="cb-c",
            amount_usd=500_000,
            round_type="Pre-seed",
            announced_at=now - timedelta(days=15),
            investors=[],
        ),
    )

    return {"alpha": alpha.id, "bravo": bravo.id, "charlie": charlie.id, "ph_launch": ph_launch.id}


# --- list_dashboard_rows --------------------------------------------------


def test_list_dashboard_rows_returns_row_per_company(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    rows = list_dashboard_rows(db)
    assert {r.name for r in rows} == {"Alpha", "Bravo", "Charlie"}


def test_latest_launch_is_most_recent(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    rows = {r.name: r for r in list_dashboard_rows(db)}
    # Alpha's most recent launch was days=-1, the PH one.
    assert rows["Alpha"].latest_launch_source == "producthunt"
    assert rows["Alpha"].latest_launch_title == "Alpha launches Alpha"


def test_is_mock_flag_true_for_any_mock_row(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    rows = {r.name: r for r in list_dashboard_rows(db)}
    assert rows["Alpha"].is_mock is True  # has mock_x + mock_crunchbase rows
    assert rows["Charlie"].is_mock is True  # has mock_crunchbase row
    assert rows["Bravo"].is_mock is False  # no launches or funding at all


def test_total_raised_sums_per_company(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    rows = {r.name: r for r in list_dashboard_rows(db)}
    assert rows["Alpha"].total_raised_usd == 10_000_000
    assert rows["Charlie"].total_raised_usd == 500_000
    assert rows["Bravo"].total_raised_usd == 0


def test_counts_of_contacts_and_drafts(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    rows = {r.name: r for r in list_dashboard_rows(db)}
    assert rows["Alpha"].n_contacts == 1
    assert rows["Alpha"].n_dm_drafts == 1
    assert rows["Bravo"].n_contacts == 0
    assert rows["Bravo"].n_dm_drafts == 0


def test_source_filter_restricts_rows(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    # Only "mock_x" → only Alpha has a mock_x launch.
    rows = list_dashboard_rows(db, sources=["mock_x"])
    assert {r.name for r in rows} == {"Alpha"}


def test_source_filter_with_producthunt(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    rows = list_dashboard_rows(db, sources=["producthunt"])
    assert {r.name for r in rows} == {"Alpha", "Charlie"}


def test_empty_source_filter_is_noop(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    rows = list_dashboard_rows(db, sources=[])
    assert {r.name for r in rows} == {"Alpha", "Bravo", "Charlie"}


# --- get_kpis -------------------------------------------------------------


def test_kpis_over_full_graph(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    kpis = get_kpis(db)
    assert kpis.total_companies == 3
    assert kpis.total_raised_usd == 10_500_000
    # Avg of [100, 40, 20] = 53.3
    assert kpis.avg_engagement == pytest.approx(53.3, rel=0.01)
    assert kpis.n_flagged_for_outreach == 1


def test_kpis_with_source_filter(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    kpis = get_kpis(db, sources=["producthunt"])
    # Only Alpha + Charlie have PH launches → total raised = 10M + 500k
    assert kpis.total_companies == 2
    assert kpis.total_raised_usd == 10_500_000


# --- get_top_raised -------------------------------------------------------


def test_top_raised_sorted_descending(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    top = get_top_raised(db, n=10)
    names = [r[0] for r in top]
    assert names == ["Alpha", "Charlie"]
    assert top[0][1] == 10_000_000
    assert top[1][1] == 500_000


def test_top_raised_respects_limit(db: sqlite3.Connection) -> None:
    _seed_full_graph(db)
    top = get_top_raised(db, n=1)
    assert len(top) == 1
    assert top[0][0] == "Alpha"


# --- get_company_detail ---------------------------------------------------


def test_company_detail_bundles_all_children(db: sqlite3.Connection) -> None:
    ids = _seed_full_graph(db)
    detail = get_company_detail(db, ids["alpha"])
    assert len(detail.launches) == 2
    assert len(detail.funding_rounds) == 1
    assert len(detail.contacts) == 1
    assert len(detail.dm_drafts) == 1


def test_company_detail_launches_sorted_by_recency(db: sqlite3.Connection) -> None:
    ids = _seed_full_graph(db)
    detail = get_company_detail(db, ids["alpha"])
    dates = [launch["posted_at"] for launch in detail.launches]
    assert dates == sorted(dates, reverse=True)


def test_company_detail_includes_draft_launch_context(db: sqlite3.Connection) -> None:
    ids = _seed_full_graph(db)
    detail = get_company_detail(db, ids["alpha"])
    draft = detail.dm_drafts[0]
    assert draft["launch_id"] == ids["ph_launch"]
    assert draft["launch_title"] == "Alpha launches Alpha"


# --- ALL_SOURCES smoke ---------------------------------------------------


def test_all_sources_matches_production_set() -> None:
    assert set(ALL_SOURCES) == {
        "producthunt",
        "mock_x",
        "mock_linkedin",
        "mock_crunchbase",
        "mock_yc",
    }
