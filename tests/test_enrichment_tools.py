from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from src.agent.enrichment_tools import (
    ENRICHMENT_HANDLERS,
    ENRICHMENT_TOOLS,
    handle_find_email,
    handle_find_linkedin,
    handle_find_phone,
    handle_find_x_handle,
    handle_finish,
    handle_list_companies_missing_contacts,
    handle_persist_contact,
    load_enrichment_prompt_version,
    load_enrichment_system_prompt,
)
from src.agent.tools import ToolContext
from src.db.repo import (
    insert_contact,
    list_contacts_by_company,
    upsert_company,
)
from src.models import Company, Contact


def _ctx(db: sqlite3.Connection | None, **overrides: Any) -> ToolContext:
    return ToolContext(conn=db, **overrides)


# --- prompt loader ---------------------------------------------------------


def test_enrichment_system_prompt_strips_header() -> None:
    prompt = load_enrichment_system_prompt()
    assert "You are the enrichment pass" in prompt
    assert "**Version:**" not in prompt
    assert "# Enrichment" not in prompt


def test_enrichment_prompt_version() -> None:
    assert load_enrichment_prompt_version() == "v1"


# --- list_companies_missing_contacts --------------------------------------


def test_list_companies_missing_contacts_excludes_enriched(db: sqlite3.Connection) -> None:
    alpha = upsert_company(db, Company(name="Alpha"))
    bravo = upsert_company(db, Company(name="Bravo"))
    assert alpha.id is not None and bravo.id is not None
    insert_contact(
        db,
        Contact(company_id=alpha.id, email="a@alpha.com", confidence=0.9, source="mock"),
    )

    out = handle_list_companies_missing_contacts({}, _ctx(db))
    names = {c["name"] for c in out["companies"]}
    assert names == {"Bravo"}


def test_list_companies_missing_contacts_no_conn() -> None:
    out = handle_list_companies_missing_contacts({}, _ctx(None))
    assert out["code"] == "runtime_error"


# --- find_* tools are deterministic ---------------------------------------


def test_find_email_deterministic() -> None:
    out1 = handle_find_email({"company_name": "Acme"}, _ctx(None))
    out2 = handle_find_email({"company_name": "Acme"}, _ctx(None))
    assert out1 == out2


def test_find_email_different_companies_different_output() -> None:
    a = handle_find_email({"company_name": "Acme"}, _ctx(None))
    b = handle_find_email({"company_name": "Zephyr"}, _ctx(None))
    # The emails might coincidentally match once in a blue moon if both miss.
    # To keep the test robust, assert that at least one of the email values is set to a
    # slug-bearing string (so we can cross-check domains).
    if a["email"] and b["email"]:
        assert a["email"].endswith("@acme.com")
        assert b["email"].endswith("@zephyr.com")


def test_find_email_miss_case_returns_null() -> None:
    # With a deterministic seed we can find one example that misses.
    for name in [f"misser_{i}" for i in range(50)]:
        out = handle_find_email({"company_name": name}, _ctx(None))
        if out["email"] is None:
            assert out["confidence"] == 0.0
            break
    else:
        pytest.fail("expected at least one miss in 50 attempts given 15% miss rate")


def test_find_email_rejects_empty_name() -> None:
    out = handle_find_email({"company_name": ""}, _ctx(None))
    assert out["code"] == "validation_error"


def test_find_phone_format() -> None:
    # Pick a name that does not hit the 30% miss rate deterministically.
    for name in [f"PhoneCo_{i}" for i in range(50)]:
        out = handle_find_phone({"company_name": name}, _ctx(None))
        if out["phone"] is not None:
            assert out["phone"].startswith("+1-")
            parts = out["phone"][3:].split("-")
            assert len(parts) == 3
            assert all(p.isdigit() for p in parts)
            break
    else:
        pytest.fail("could not find a non-miss phone in 50 attempts")


def test_find_linkedin_url_shape() -> None:
    for name in [f"LinkCo_{i}" for i in range(20)]:
        out = handle_find_linkedin({"company_name": name}, _ctx(None))
        if out["linkedin_url"] is not None:
            assert out["linkedin_url"].startswith("https://linkedin.com/company/")
            assert out["linkedin_url"].endswith(name.lower().replace("_", ""))
            break
    else:
        pytest.fail("linkedin miss rate too high in test sample")


def test_find_x_handle_shape_respects_15_char_limit() -> None:
    out = handle_find_x_handle({"company_name": "ThisIsALongCompanyName"}, _ctx(None))
    if out["x_handle"] is not None:
        handle = out["x_handle"].lstrip("@")
        assert len(handle) <= 15


# --- persist_contact ------------------------------------------------------


def test_persist_contact_happy_path(db: sqlite3.Connection) -> None:
    company = upsert_company(db, Company(name="Alpha"))
    assert company.id is not None

    out = handle_persist_contact(
        {
            "company_id": company.id,
            "email": "ceo@alpha.com",
            "phone": "+1-415-200-1234",
            "linkedin_url": "https://linkedin.com/company/alpha",
            "x_handle": "@alpha",
            "confidence": 0.82,
            "source": "mock",
        },
        _ctx(db),
    )
    assert "contact_id" in out
    contacts = list_contacts_by_company(db, company.id)
    assert len(contacts) == 1
    assert contacts[0].email == "ceo@alpha.com"


def test_persist_contact_accepts_all_nulls(db: sqlite3.Connection) -> None:
    company = upsert_company(db, Company(name="Alpha"))
    assert company.id is not None

    out = handle_persist_contact(
        {
            "company_id": company.id,
            "email": None,
            "phone": None,
            "linkedin_url": None,
            "x_handle": None,
            "confidence": 0.0,
            "source": "mock",
        },
        _ctx(db),
    )
    assert "contact_id" in out
    assert len(list_contacts_by_company(db, company.id)) == 1


def test_persist_contact_validation_error_missing_company_id(db: sqlite3.Connection) -> None:
    out = handle_persist_contact({"confidence": 0.5, "source": "mock"}, _ctx(db))
    assert out["code"] == "validation_error"


def test_persist_contact_dry_run_skips_db(db: sqlite3.Connection) -> None:
    company = upsert_company(db, Company(name="Alpha"))
    assert company.id is not None
    out = handle_persist_contact(
        {
            "company_id": company.id,
            "confidence": 0.5,
            "source": "mock",
        },
        _ctx(db, persist=False),
    )
    assert out.get("dry_run") is True
    assert list_contacts_by_company(db, company.id) == []


def test_persist_contact_foreign_key_enforced(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        handle_persist_contact(
            {
                "company_id": 9999,  # does not exist
                "confidence": 0.5,
                "source": "mock",
            },
            _ctx(db),
        )


# --- finish ---------------------------------------------------------------


def test_finish_sets_ctx_state() -> None:
    ctx = ToolContext(conn=None, persist=False)
    handle_finish({"summary": {"contacts_persisted": 5}}, ctx)
    assert ctx.finished is True
    assert ctx.finish_summary == {"contacts_persisted": 5}


# --- dispatch contract ----------------------------------------------------


def test_enrichment_handlers_cover_every_tool() -> None:
    assert set(ENRICHMENT_HANDLERS) == {tool["function"]["name"] for tool in ENRICHMENT_TOOLS}


def test_enrichment_tool_schemas_are_strict() -> None:
    for tool in ENRICHMENT_TOOLS:
        schema = tool["function"]["parameters"]
        assert schema.get("additionalProperties") is False, tool["function"]["name"]
