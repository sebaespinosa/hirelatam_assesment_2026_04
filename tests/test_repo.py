from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from src.db.repo import (
    get_company_by_id,
    get_company_by_name,
    insert_contact,
    insert_dm_draft,
    insert_funding,
    insert_launch,
    list_companies,
    list_contacts_by_company,
    list_dm_drafts_by_launch,
    list_funding_rounds,
    list_launches,
    upsert_company,
)
from src.models import Company, Contact, DmDraft, FundingRound, Launch


def test_upsert_company_roundtrip(db: sqlite3.Connection) -> None:
    """Phase 1 done-when: upsert_company → fetch → pydantic validates."""
    stored = upsert_company(
        db, Company(name="Acme", website="https://acme.test", description="rockets")
    )
    assert stored.id is not None

    fetched = get_company_by_name(db, "Acme")
    assert fetched is not None
    assert fetched == stored  # Pydantic equality validates all fields survived the round trip


def test_upsert_company_preserves_id_on_conflict(db: sqlite3.Connection) -> None:
    first = upsert_company(db, Company(name="Acme", description="v1"))
    second = upsert_company(db, Company(name="Acme", description="v2"))
    assert second.id == first.id
    assert second.description == "v2"


def test_upsert_company_does_not_clobber_with_nulls(db: sqlite3.Connection) -> None:
    upsert_company(db, Company(name="Acme", website="https://acme.test"))
    second = upsert_company(db, Company(name="Acme"))  # no website
    assert second.website == "https://acme.test"  # COALESCE preserves it


def test_insert_launch_idempotent_on_source_source_id(db: sqlite3.Connection) -> None:
    company = upsert_company(db, Company(name="Acme"))
    assert company.id is not None

    launch = Launch(
        company_id=company.id,
        source="producthunt",
        source_id="ph-1",
        title="Acme Rocket",
        url="https://ph.test/acme",
        posted_at=datetime.now(UTC),
        engagement_score=42.0,
        engagement_breakdown={"votes": 100, "comments": 10},
        raw_payload={"note": "fresh ingest"},
    )
    first = insert_launch(db, launch)

    bumped = launch.model_copy(update={"engagement_score": 100.0})
    second = insert_launch(db, bumped)
    assert second.id == first.id
    assert second.engagement_score == 100.0

    assert len(list_launches(db, company_id=company.id)) == 1


def test_insert_funding_preserves_json_investors(db: sqlite3.Connection) -> None:
    company = upsert_company(db, Company(name="Acme"))
    assert company.id is not None

    round_ = FundingRound(
        company_id=company.id,
        source="crunchbase",
        source_id="cb-1",
        amount_usd=10_000_000,
        round_type="Series A",
        announced_at=datetime.now(UTC),
        investors=["Sequoia", "a16z"],
        raw_payload={"note": "mocked"},
    )
    stored = insert_funding(db, round_)
    assert stored.investors == ["Sequoia", "a16z"]

    rounds = list_funding_rounds(db, company_id=company.id)
    assert len(rounds) == 1
    assert rounds[0].investors == ["Sequoia", "a16z"]


def test_insert_contact_and_read_by_company(db: sqlite3.Connection) -> None:
    company = upsert_company(db, Company(name="Acme"))
    assert company.id is not None

    insert_contact(
        db,
        Contact(
            company_id=company.id,
            email="ceo@acme.test",
            linkedin_url="https://linkedin.com/company/acme",
            confidence=0.8,
            source="mock",
        ),
    )
    contacts = list_contacts_by_company(db, company.id)
    assert len(contacts) == 1
    assert contacts[0].email == "ceo@acme.test"


def test_insert_dm_draft_and_read_by_launch(db: sqlite3.Connection) -> None:
    company = upsert_company(db, Company(name="Acme"))
    assert company.id is not None
    launch = insert_launch(
        db,
        Launch(
            company_id=company.id,
            source="producthunt",
            source_id="ph-1",
            title="Acme Rocket",
            posted_at=datetime.now(UTC),
        ),
    )
    assert launch.id is not None

    insert_dm_draft(
        db,
        DmDraft(
            launch_id=launch.id,
            subject="Loved your launch",
            body="Hey — saw Acme Rocket, quick thought...",
            tone="warm",
            prompt_version="v1",
        ),
    )
    drafts = list_dm_drafts_by_launch(db, launch.id)
    assert len(drafts) == 1
    assert drafts[0].subject == "Loved your launch"


def test_foreign_key_enforced_on_launch(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        insert_launch(
            db,
            Launch(
                company_id=9999,  # does not exist
                source="producthunt",
                source_id="ph-ghost",
                title="Ghost",
                posted_at=datetime.now(UTC),
            ),
        )


def test_list_companies_orders_by_name(db: sqlite3.Connection) -> None:
    upsert_company(db, Company(name="Charlie"))
    upsert_company(db, Company(name="Alpha"))
    upsert_company(db, Company(name="Bravo"))
    names = [c.name for c in list_companies(db)]
    assert names == ["Alpha", "Bravo", "Charlie"]


def test_get_company_by_id_roundtrip(db: sqlite3.Connection) -> None:
    stored = upsert_company(db, Company(name="Acme"))
    assert stored.id is not None
    fetched = get_company_by_id(db, stored.id)
    assert fetched == stored
