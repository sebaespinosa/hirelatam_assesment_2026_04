"""Heuristics for flagging under-performing launches as DM-draft candidates.

"Under-performing" = ``engagement_score < P25`` of launches from the same source
within the recent window. Grouping by source matters — a LinkedIn launch with
200 reactions is an outlier-low compared to LinkedIn peers, but would look
healthy next to a Product Hunt post that has 300 upvotes.

The percentile is computed in Python because SQLite ships no native
``percentile_cont``. All launches in the window are fetched, bucketed by
source, and ranked — this scales fine for the demo dataset (< 10k rows).
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

DEFAULT_WINDOW_DAYS = 60
DEFAULT_PERCENTILE = 25
DEFAULT_MAX_COUNT = 20


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile. Returns 0.0 on empty input."""
    if not values:
        return 0.0
    ranked = sorted(values)
    k = (len(ranked) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(ranked) - 1)
    if f == c:
        return ranked[f]
    return ranked[f] + (k - f) * (ranked[c] - ranked[f])


def list_underperforming_launches(
    conn: sqlite3.Connection,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_count: int = DEFAULT_MAX_COUNT,
    percentile_pct: float = DEFAULT_PERCENTILE,
) -> list[dict[str, Any]]:
    """Return launches whose engagement_score is below their source's P25 within the window.

    Rows are enriched with company name/website and the first available contact
    channels (email / linkedin_url / x_handle) so the DM-draft agent has
    everything it needs in one round-trip.
    """
    rows = conn.execute(
        """
        SELECT
            l.id               AS launch_id,
            l.source           AS source,
            l.source_id        AS source_id,
            l.title            AS launch_title,
            l.url              AS launch_url,
            l.posted_at        AS launch_posted_at,
            l.engagement_score AS engagement_score,
            l.engagement_breakdown AS engagement_breakdown,
            c.id               AS company_id,
            c.name             AS company_name,
            c.website          AS company_website,
            ct.email           AS contact_email,
            ct.linkedin_url    AS contact_linkedin_url,
            ct.x_handle        AS contact_x_handle,
            ct.confidence      AS contact_confidence
        FROM launch l
        JOIN company c ON c.id = l.company_id
        LEFT JOIN contact ct ON ct.company_id = c.id
        WHERE l.posted_at >= date('now', ?)
        ORDER BY l.source, l.engagement_score
        """,
        (f"-{window_days} days",),
    ).fetchall()

    by_source: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)

    results: list[dict[str, Any]] = []
    for source_rows in by_source.values():
        scores = [r["engagement_score"] for r in source_rows]
        threshold = percentile(scores, percentile_pct)
        for row in source_rows:
            if row["engagement_score"] < threshold:
                results.append(_row_to_dict(row, threshold=threshold))

    results.sort(key=lambda r: r["engagement_score"])
    return results[:max_count]


def _row_to_dict(row: sqlite3.Row, *, threshold: float) -> dict[str, Any]:
    raw = row["engagement_breakdown"]
    try:
        engagement_breakdown = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        engagement_breakdown = {}
    return {
        "launch_id": row["launch_id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "launch_title": row["launch_title"],
        "launch_url": row["launch_url"],
        "launch_posted_at": row["launch_posted_at"],
        "engagement_score": row["engagement_score"],
        "engagement_breakdown": engagement_breakdown,
        "source_p25_threshold": threshold,
        "company_id": row["company_id"],
        "company_name": row["company_name"],
        "company_website": row["company_website"],
        "contact": {
            "email": row["contact_email"],
            "linkedin_url": row["contact_linkedin_url"],
            "x_handle": row["contact_x_handle"],
            "confidence": row["contact_confidence"],
        },
    }
