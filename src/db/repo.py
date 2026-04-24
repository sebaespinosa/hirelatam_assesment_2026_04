"""Typed persistence layer over SQLite.

All writes go through the upsert/insert helpers here. The agent never
constructs SQL itself — it passes Pydantic objects to these functions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from src.models import Company, Contact, DmDraft, FundingRound, Launch


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_company(row: sqlite3.Row) -> Company:
    return Company(
        id=row["id"],
        name=row["name"],
        website=row["website"],
        description=row["description"],
        created_at=_dt(row["created_at"]),
    )


def _row_to_launch(row: sqlite3.Row) -> Launch:
    return Launch(
        id=row["id"],
        company_id=row["company_id"],
        source=row["source"],
        source_id=row["source_id"],
        title=row["title"],
        url=row["url"],
        posted_at=_dt(row["posted_at"]),
        engagement_score=row["engagement_score"],
        engagement_breakdown=json.loads(row["engagement_breakdown"]),
        raw_payload=json.loads(row["raw_payload"]),
    )


def _row_to_funding(row: sqlite3.Row) -> FundingRound:
    return FundingRound(
        id=row["id"],
        company_id=row["company_id"],
        source=row["source"],
        source_id=row["source_id"],
        amount_usd=row["amount_usd"],
        round_type=row["round_type"],
        announced_at=_dt(row["announced_at"]),
        investors=json.loads(row["investors"]),
        raw_payload=json.loads(row["raw_payload"]),
    )


def _row_to_contact(row: sqlite3.Row) -> Contact:
    return Contact(
        id=row["id"],
        company_id=row["company_id"],
        email=row["email"],
        phone=row["phone"],
        linkedin_url=row["linkedin_url"],
        x_handle=row["x_handle"],
        confidence=row["confidence"],
        source=row["source"],
    )


def _row_to_dm_draft(row: sqlite3.Row) -> DmDraft:
    return DmDraft(
        id=row["id"],
        launch_id=row["launch_id"],
        subject=row["subject"],
        body=row["body"],
        tone=row["tone"],
        generated_at=_dt(row["generated_at"]),
        prompt_version=row["prompt_version"],
    )


# --- writes -----------------------------------------------------------------


def upsert_company(conn: sqlite3.Connection, company: Company) -> Company:
    """Insert by name; on name collision, fill in missing website/description."""
    cursor = conn.execute(
        """
        INSERT INTO company (name, website, description, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            website = COALESCE(excluded.website, company.website),
            description = COALESCE(excluded.description, company.description)
        RETURNING id, name, website, description, created_at
        """,
        (company.name, company.website, company.description, _iso(company.created_at)),
    )
    row = cursor.fetchone()
    conn.commit()
    return _row_to_company(row)


def insert_launch(conn: sqlite3.Connection, launch: Launch) -> Launch:
    """Idempotent on (source, source_id); re-inserts refresh engagement + payload."""
    cursor = conn.execute(
        """
        INSERT INTO launch (
            company_id, source, source_id, title, url, posted_at,
            engagement_score, engagement_breakdown, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            posted_at = excluded.posted_at,
            engagement_score = excluded.engagement_score,
            engagement_breakdown = excluded.engagement_breakdown,
            raw_payload = excluded.raw_payload
        RETURNING id, company_id, source, source_id, title, url, posted_at,
                  engagement_score, engagement_breakdown, raw_payload
        """,
        (
            launch.company_id,
            launch.source,
            launch.source_id,
            launch.title,
            launch.url,
            _iso(launch.posted_at),
            launch.engagement_score,
            json.dumps(launch.engagement_breakdown),
            json.dumps(launch.raw_payload),
        ),
    )
    row = cursor.fetchone()
    conn.commit()
    return _row_to_launch(row)


def insert_funding(conn: sqlite3.Connection, round_: FundingRound) -> FundingRound:
    """Idempotent on (source, source_id)."""
    cursor = conn.execute(
        """
        INSERT INTO funding_round (
            company_id, source, source_id, amount_usd, round_type,
            announced_at, investors, raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            amount_usd = excluded.amount_usd,
            round_type = excluded.round_type,
            announced_at = excluded.announced_at,
            investors = excluded.investors,
            raw_payload = excluded.raw_payload
        RETURNING id, company_id, source, source_id, amount_usd, round_type,
                  announced_at, investors, raw_payload
        """,
        (
            round_.company_id,
            round_.source,
            round_.source_id,
            round_.amount_usd,
            round_.round_type,
            _iso(round_.announced_at),
            json.dumps(round_.investors),
            json.dumps(round_.raw_payload),
        ),
    )
    row = cursor.fetchone()
    conn.commit()
    return _row_to_funding(row)


def insert_contact(conn: sqlite3.Connection, contact: Contact) -> Contact:
    cursor = conn.execute(
        """
        INSERT INTO contact (
            company_id, email, phone, linkedin_url, x_handle, confidence, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id, company_id, email, phone, linkedin_url, x_handle, confidence, source
        """,
        (
            contact.company_id,
            contact.email,
            contact.phone,
            contact.linkedin_url,
            contact.x_handle,
            contact.confidence,
            contact.source,
        ),
    )
    row = cursor.fetchone()
    conn.commit()
    return _row_to_contact(row)


def insert_dm_draft(conn: sqlite3.Connection, draft: DmDraft) -> DmDraft:
    cursor = conn.execute(
        """
        INSERT INTO dm_draft (
            launch_id, subject, body, tone, generated_at, prompt_version
        )
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id, launch_id, subject, body, tone, generated_at, prompt_version
        """,
        (
            draft.launch_id,
            draft.subject,
            draft.body,
            draft.tone,
            _iso(draft.generated_at),
            draft.prompt_version,
        ),
    )
    row = cursor.fetchone()
    conn.commit()
    return _row_to_dm_draft(row)


# --- reads ------------------------------------------------------------------


def get_company_by_name(conn: sqlite3.Connection, name: str) -> Company | None:
    row = conn.execute("SELECT * FROM company WHERE name = ?", (name,)).fetchone()
    return _row_to_company(row) if row else None


def get_company_by_id(conn: sqlite3.Connection, company_id: int) -> Company | None:
    row = conn.execute("SELECT * FROM company WHERE id = ?", (company_id,)).fetchone()
    return _row_to_company(row) if row else None


def list_companies(conn: sqlite3.Connection) -> list[Company]:
    rows = conn.execute("SELECT * FROM company ORDER BY name").fetchall()
    return [_row_to_company(r) for r in rows]


def list_launches(
    conn: sqlite3.Connection,
    *,
    company_id: int | None = None,
    source: str | None = None,
) -> list[Launch]:
    sql = "SELECT * FROM launch WHERE 1=1"
    params: list[object] = []
    if company_id is not None:
        sql += " AND company_id = ?"
        params.append(company_id)
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY posted_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_launch(r) for r in rows]


def list_funding_rounds(
    conn: sqlite3.Connection, *, company_id: int | None = None
) -> list[FundingRound]:
    if company_id is None:
        rows = conn.execute(
            "SELECT * FROM funding_round ORDER BY announced_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM funding_round WHERE company_id = ? ORDER BY announced_at DESC",
            (company_id,),
        ).fetchall()
    return [_row_to_funding(r) for r in rows]


def list_contacts_by_company(conn: sqlite3.Connection, company_id: int) -> list[Contact]:
    rows = conn.execute(
        "SELECT * FROM contact WHERE company_id = ? ORDER BY confidence DESC",
        (company_id,),
    ).fetchall()
    return [_row_to_contact(r) for r in rows]


def list_dm_drafts_by_launch(conn: sqlite3.Connection, launch_id: int) -> list[DmDraft]:
    rows = conn.execute(
        "SELECT * FROM dm_draft WHERE launch_id = ? ORDER BY generated_at DESC",
        (launch_id,),
    ).fetchall()
    return [_row_to_dm_draft(r) for r in rows]
