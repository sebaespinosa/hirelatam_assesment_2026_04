"""Join-heavy read queries backing the Streamlit dashboard.

Pure Python — no ``streamlit`` import — so these are testable with the
standard ``conftest.db`` fixture and reusable for any future consumer.

All queries accept an optional ``sources`` filter. A company is included iff
at least one of its rows (launch or funding_round) matches one of the given
sources. If ``sources`` is ``None`` or empty, no filter is applied.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

ALL_SOURCES = ("producthunt", "mock_x", "mock_linkedin", "mock_crunchbase", "mock_yc")


@dataclass
class DashboardRow:
    company_id: int
    name: str
    website: str | None
    description: str | None
    is_mock: bool
    latest_launch_title: str | None
    latest_launch_source: str | None
    latest_launch_engagement: float | None
    latest_launch_posted_at: str | None
    total_raised_usd: int
    last_round_type: str | None
    last_round_amount_usd: int | None
    last_round_announced_at: str | None
    n_contacts: int
    n_dm_drafts: int


@dataclass
class Kpis:
    total_companies: int
    total_raised_usd: int
    avg_engagement: float
    n_flagged_for_outreach: int


@dataclass
class CompanyDetail:
    company_id: int
    launches: list[dict[str, Any]]
    funding_rounds: list[dict[str, Any]]
    contacts: list[dict[str, Any]]
    dm_drafts: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _source_filter_clause(sources: list[str] | tuple[str, ...] | None) -> tuple[str, list[Any]]:
    """Build a ``WHERE c.id IN (...)`` clause restricting to selected sources."""
    if not sources:
        return "", []
    placeholders = ",".join("?" * len(sources))
    clause = f"""
        c.id IN (
            SELECT company_id FROM launch WHERE source IN ({placeholders})
            UNION
            SELECT company_id FROM funding_round WHERE source IN ({placeholders})
        )
    """
    return clause, [*sources, *sources]


def _row_to_dashboard(row: sqlite3.Row) -> DashboardRow:
    return DashboardRow(
        company_id=row["company_id"],
        name=row["name"],
        website=row["website"],
        description=row["description"],
        is_mock=bool(row["is_mock"]),
        latest_launch_title=row["latest_launch_title"],
        latest_launch_source=row["latest_launch_source"],
        latest_launch_engagement=row["latest_launch_engagement"],
        latest_launch_posted_at=row["latest_launch_posted_at"],
        total_raised_usd=int(row["total_raised_usd"] or 0),
        last_round_type=row["last_round_type"],
        last_round_amount_usd=row["last_round_amount_usd"],
        last_round_announced_at=row["last_round_announced_at"],
        n_contacts=int(row["n_contacts"] or 0),
        n_dm_drafts=int(row["n_dm_drafts"] or 0),
    )


# ---------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------


def list_dashboard_rows(
    conn: sqlite3.Connection,
    *,
    sources: list[str] | tuple[str, ...] | None = None,
) -> list[DashboardRow]:
    """One row per company with latest-launch, total-raised, and flag counters."""
    filter_clause, filter_params = _source_filter_clause(sources)
    where = f"WHERE {filter_clause}" if filter_clause else ""

    sql = f"""
        SELECT
            c.id AS company_id,
            c.name,
            c.website,
            c.description,
            CASE WHEN EXISTS (
                SELECT 1 FROM launch lm
                WHERE lm.company_id = c.id AND lm.source LIKE 'mock_%'
            ) OR EXISTS (
                SELECT 1 FROM funding_round fm
                WHERE fm.company_id = c.id AND fm.source LIKE 'mock_%'
            ) THEN 1 ELSE 0 END AS is_mock,
            (SELECT l.title FROM launch l WHERE l.company_id = c.id
                ORDER BY l.posted_at DESC LIMIT 1) AS latest_launch_title,
            (SELECT l.source FROM launch l WHERE l.company_id = c.id
                ORDER BY l.posted_at DESC LIMIT 1) AS latest_launch_source,
            (SELECT l.engagement_score FROM launch l WHERE l.company_id = c.id
                ORDER BY l.posted_at DESC LIMIT 1) AS latest_launch_engagement,
            (SELECT l.posted_at FROM launch l WHERE l.company_id = c.id
                ORDER BY l.posted_at DESC LIMIT 1) AS latest_launch_posted_at,
            COALESCE((
                SELECT SUM(f.amount_usd) FROM funding_round f WHERE f.company_id = c.id
            ), 0) AS total_raised_usd,
            (SELECT f.round_type FROM funding_round f WHERE f.company_id = c.id
                ORDER BY f.announced_at DESC LIMIT 1) AS last_round_type,
            (SELECT f.amount_usd FROM funding_round f WHERE f.company_id = c.id
                ORDER BY f.announced_at DESC LIMIT 1) AS last_round_amount_usd,
            (SELECT f.announced_at FROM funding_round f WHERE f.company_id = c.id
                ORDER BY f.announced_at DESC LIMIT 1) AS last_round_announced_at,
            (SELECT COUNT(*) FROM contact ct WHERE ct.company_id = c.id) AS n_contacts,
            (SELECT COUNT(*) FROM dm_draft d
                JOIN launch l2 ON l2.id = d.launch_id
                WHERE l2.company_id = c.id) AS n_dm_drafts
        FROM company c
        {where}
        ORDER BY c.name
    """
    rows = conn.execute(sql, filter_params).fetchall()
    return [_row_to_dashboard(r) for r in rows]


def get_kpis(
    conn: sqlite3.Connection,
    *,
    sources: list[str] | tuple[str, ...] | None = None,
) -> Kpis:
    filter_clause, filter_params = _source_filter_clause(sources)
    where = f"WHERE {filter_clause}" if filter_clause else ""

    total_companies = conn.execute(
        f"SELECT COUNT(*) FROM company c {where}", filter_params
    ).fetchone()[0]

    # Funding / engagement aggregates restrict to the filtered company set.
    total_raised = conn.execute(
        f"""
        SELECT COALESCE(SUM(f.amount_usd), 0) FROM funding_round f
        WHERE f.company_id IN (SELECT c.id FROM company c {where})
        """,
        filter_params,
    ).fetchone()[0]

    avg_eng_row = conn.execute(
        f"""
        SELECT AVG(l.engagement_score) FROM launch l
        WHERE l.company_id IN (SELECT c.id FROM company c {where})
        """,
        filter_params,
    ).fetchone()
    avg_engagement = float(avg_eng_row[0]) if avg_eng_row[0] is not None else 0.0

    n_flagged = conn.execute(
        f"""
        SELECT COUNT(DISTINCT d.launch_id) FROM dm_draft d
        JOIN launch l ON l.id = d.launch_id
        WHERE l.company_id IN (SELECT c.id FROM company c {where})
        """,
        filter_params,
    ).fetchone()[0]

    return Kpis(
        total_companies=int(total_companies or 0),
        total_raised_usd=int(total_raised or 0),
        avg_engagement=round(avg_engagement, 1),
        n_flagged_for_outreach=int(n_flagged or 0),
    )


def get_top_raised(conn: sqlite3.Connection, *, n: int = 10) -> list[tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT c.name, SUM(f.amount_usd) AS total
        FROM funding_round f
        JOIN company c ON c.id = f.company_id
        GROUP BY c.id
        ORDER BY total DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    return [(r["name"], int(r["total"] or 0)) for r in rows]


def get_company_detail(conn: sqlite3.Connection, company_id: int) -> CompanyDetail:
    launch_rows = conn.execute(
        """
        SELECT id, source, source_id, title, url, posted_at, engagement_score,
               engagement_breakdown, raw_payload
        FROM launch WHERE company_id = ? ORDER BY posted_at DESC
        """,
        (company_id,),
    ).fetchall()
    launches = []
    for r in launch_rows:
        launches.append(
            {
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "title": r["title"],
                "url": r["url"],
                "posted_at": r["posted_at"],
                "engagement_score": r["engagement_score"],
                "engagement_breakdown": _safe_json(r["engagement_breakdown"]),
                "classification": _safe_json(r["raw_payload"]).get("_classification"),
            }
        )

    funding_rows = conn.execute(
        """
        SELECT source, amount_usd, round_type, announced_at, investors
        FROM funding_round WHERE company_id = ? ORDER BY announced_at DESC
        """,
        (company_id,),
    ).fetchall()
    funding_rounds = [
        {
            "source": r["source"],
            "round_type": r["round_type"],
            "amount_usd": r["amount_usd"],
            "announced_at": r["announced_at"],
            "investors": ", ".join(_safe_json(r["investors"]) or []),
        }
        for r in funding_rows
    ]

    contact_rows = conn.execute(
        """
        SELECT email, phone, linkedin_url, x_handle, confidence, source
        FROM contact WHERE company_id = ? ORDER BY confidence DESC
        """,
        (company_id,),
    ).fetchall()
    contacts = [dict(r) for r in contact_rows]

    dm_draft_rows = conn.execute(
        """
        SELECT d.id, d.subject, d.body, d.tone, d.generated_at, d.prompt_version,
               l.title AS launch_title, l.id AS launch_id
        FROM dm_draft d
        JOIN launch l ON l.id = d.launch_id
        WHERE l.company_id = ?
        ORDER BY d.generated_at DESC
        """,
        (company_id,),
    ).fetchall()
    dm_drafts = [dict(r) for r in dm_draft_rows]

    return CompanyDetail(
        company_id=company_id,
        launches=launches,
        funding_rounds=funding_rounds,
        contacts=contacts,
        dm_drafts=dm_drafts,
    )


def _safe_json(value: Any) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
