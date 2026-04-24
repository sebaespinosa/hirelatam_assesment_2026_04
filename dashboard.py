"""Read-only Streamlit UI over the SQLite database.

Run: ``make dashboard`` or ``uv run streamlit run dashboard.py``.

Two tabs:
- **Dashboard** — KPIs, top-10 funding chart, company summary table, per-company
  detail with Launches / Funding / Contacts / DM drafts sub-tabs.
- **Agent Run Log** — turn-by-turn event viewer over ``data/runs/*.jsonl``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.dashboard.queries import (
    ALL_SOURCES,
    DashboardRow,
    get_company_detail,
    get_kpis,
    get_top_raised,
    list_dashboard_rows,
)
from src.dashboard.run_log import list_runs, load_run, summarize_run
from src.db import get_connection

st.set_page_config(
    page_title="Launch & Fundraise Intelligence",
    page_icon="🚀",
    layout="wide",
)


@st.cache_resource
def _conn():
    # check_same_thread=False: Streamlit uses a fresh thread per rerun, and
    # @st.cache_resource holds one connection across all of them. Safe because
    # the dashboard is read-only and single-user.
    return get_connection(check_same_thread=False)


conn = _conn()


def _mock_badge(is_mock: bool) -> str:
    return " :orange-badge[MOCK]" if is_mock else ""


# ---------------------------------------------------------------------------
# Dashboard tab
# ---------------------------------------------------------------------------


def _render_dashboard_tab() -> None:
    with st.sidebar:
        st.header("Filters")
        sources = st.multiselect(
            "Sources",
            options=list(ALL_SOURCES),
            default=list(ALL_SOURCES),
            help="Include a company if any of its rows match the selected sources.",
        )
        st.divider()
        st.caption(
            "**Regenerate data from the terminal:**\n"
            "- `make run-agent` — ingestion + classifier\n"
            "- `make run-enrichment` — contact lookups\n"
            "- `make run-dm-drafts` — outreach drafts"
        )

    st.title("Launch & Fundraise Intelligence")
    st.caption(
        "A read-only snapshot of what the ingestion, enrichment, and DM-draft "
        "agents produced. Rows tagged :orange-badge[MOCK] come from generated "
        "seed data; every other row is live Product Hunt."
    )

    kpis = get_kpis(conn, sources=sources or None)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies tracked", f"{kpis.total_companies:,}")
    c2.metric("Total raised", f"${kpis.total_raised_usd:,}")
    c3.metric("Avg engagement / launch", f"{kpis.avg_engagement:,.0f}")
    c4.metric("Launches flagged for outreach", kpis.n_flagged_for_outreach)

    st.divider()
    st.subheader("Top 10 companies by total raised")
    top = get_top_raised(conn, n=10)
    if top:
        df = pd.DataFrame(top, columns=["company", "total_raised_usd"]).set_index("company")
        st.bar_chart(df, height=300)
    else:
        st.info("No funding data yet. Run `make run-agent` to ingest fundraise records.")

    st.divider()
    st.subheader("Companies")
    rows = list_dashboard_rows(conn, sources=sources or None)
    if not rows:
        st.info("No data matches the selected filters.")
        return

    st.dataframe(_rows_to_table(rows), width="stretch", hide_index=True)

    st.divider()
    st.subheader("Company detail")
    name_to_row = {r.name: r for r in rows}
    selected_name = st.selectbox("Select a company", list(name_to_row.keys()))
    if selected_name:
        _render_company_detail(name_to_row[selected_name])


def _rows_to_table(rows: list[DashboardRow]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for r in rows:
        last_round = "—"
        if r.last_round_amount_usd:
            last_round = f"{r.last_round_type or '—'} · ${r.last_round_amount_usd:,}"
        records.append(
            {
                "Company": f"{r.name}{_mock_badge(r.is_mock)}",
                "Latest launch": (r.latest_launch_title or "—")[:80],
                "Engagement": r.latest_launch_engagement,
                "Total raised (USD)": r.total_raised_usd or None,
                "Last round": last_round,
                "Contacts": "✓" if r.n_contacts else "—",
                "DM draft": "✓" if r.n_dm_drafts else "—",
            }
        )
    return pd.DataFrame(records)


def _render_company_detail(row: DashboardRow) -> None:
    detail = get_company_detail(conn, row.company_id)
    st.markdown(f"### {row.name}{_mock_badge(row.is_mock)}")
    if row.description:
        st.caption(row.description)
    if row.website:
        st.markdown(f"[{row.website}]({row.website})")

    launches_tab, funding_tab, contacts_tab, drafts_tab = st.tabs(
        ["Launches", "Funding", "Contacts", "DM drafts"]
    )

    with launches_tab:
        if not detail.launches:
            st.info("No launches for this company.")
        for launch in detail.launches:
            badge = _mock_badge(launch["source"].startswith("mock_"))
            st.markdown(f"**{launch['title']}**{badge}")
            st.caption(
                f"{launch['source']} · {launch['posted_at']} · engagement "
                f"{launch['engagement_score']:g}"
            )
            if launch.get("url"):
                st.markdown(f"[{launch['url']}]({launch['url']})")
            if launch.get("engagement_breakdown"):
                st.caption(_format_breakdown(launch["engagement_breakdown"]))
            if launch.get("classification"):
                cls = launch["classification"]
                st.caption(
                    f"Classifier: **{cls.get('launch_type') or '—'}** "
                    f"(confidence {cls.get('confidence', 0):.2f}) — {cls.get('reasoning', '')}"
                )
            st.markdown("---")

    with funding_tab:
        if not detail.funding_rounds:
            st.info("No funding rounds.")
        else:
            df = pd.DataFrame(detail.funding_rounds)
            st.dataframe(df, width="stretch", hide_index=True)

    with contacts_tab:
        if not detail.contacts:
            st.info("No contact rows yet. Run `make run-enrichment` to populate.")
        for contact in detail.contacts:
            col1, col2, col3, col4 = st.columns(4)
            col1.markdown(f"**📧** {contact.get('email') or '—'}")
            col2.markdown(f"**📞** {contact.get('phone') or '—'}")
            col3.markdown(
                f"**🔗** {contact.get('linkedin_url') or '—'}"
            )
            col4.markdown(f"**𝕏** {contact.get('x_handle') or '—'}")
            st.caption(
                f"confidence {contact.get('confidence', 0):.2f} · source "
                f":orange-badge[{contact.get('source', '')}]"
            )
            st.markdown("---")

    with drafts_tab:
        if not detail.dm_drafts:
            st.info("No DM drafts yet. Run `make run-dm-drafts` to generate.")
        for draft in detail.dm_drafts:
            st.markdown(
                f"**{draft['subject']}** · tone `{draft['tone']}` · "
                f"prompt `{draft['prompt_version']}`"
            )
            st.caption(f"For launch: {draft['launch_title']}")
            st.text_area(
                "body",
                value=draft["body"],
                height=160,
                key=f"draft_body_{draft['id']}",
                label_visibility="collapsed",
            )
            st.markdown("---")


def _format_breakdown(breakdown: dict[str, Any]) -> str:
    parts = []
    for key, value in breakdown.items():
        if value is None:
            continue
        parts.append(f"{key}: {value}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Agent Run Log tab
# ---------------------------------------------------------------------------


def _render_run_log_tab() -> None:
    st.title("Agent Run Log")
    st.caption(
        "Turn-by-turn JSONL from `data/runs/`. Every assistant message and tool "
        "call is recorded — this is the audit trail for the AI-engineering pipeline."
    )

    runs = list_runs()
    if not runs:
        st.info("No agent runs yet. Run `make run-agent` to generate one.")
        return

    labels = [r.label for r in runs[:40]]
    idx = st.selectbox(
        "Run",
        options=list(range(len(labels))),
        format_func=lambda i: labels[i],
    )
    run = runs[idx]
    events = load_run(run.path)
    summary = summarize_run(events)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Turns", summary.n_turns)
    c2.metric("Tool calls", summary.n_tool_calls)
    c3.metric("Duration", f"{summary.elapsed_ms / 1000:.1f}s")
    c4.metric("Status", "✓ finished" if summary.finished else "⚠ incomplete")
    c5.metric("Model", summary.model or "—")

    st.divider()
    st.subheader("Tool call breakdown")
    if summary.tool_histogram:
        st.bar_chart(pd.Series(summary.tool_histogram, name="count"))
    else:
        st.info("No tool calls logged.")

    st.divider()
    st.subheader("Events")
    for event in events:
        _render_event(event)


def _render_event(event: dict[str, Any]) -> None:
    event_type = event.get("event", "?")
    turn = event.get("turn", "—")

    if event_type == "run_start":
        st.markdown(
            f"🟢 **run_start** — model `{event.get('model')}` · prompt "
            f"`{event.get('prompt_version')}` · max_turns {event.get('max_turns')} · "
            f"persist {event.get('persist')}"
        )
        return
    if event_type == "finish":
        st.markdown(f"🏁 **finish** · turn {turn}")
        with st.expander("summary", expanded=False):
            st.json(event.get("summary") or {}, expanded=False)
        return
    if event_type == "max_turns_reached":
        st.markdown(
            f"⚠️ **max_turns_reached** — stopped after {event.get('turns')} "
            f"turns, {event.get('tool_calls')} tool calls"
        )
        return
    if event_type == "assistant":
        label = (
            f"💬 turn {turn} · assistant · finish `{event.get('finish_reason')}` · "
            f"{event.get('tool_calls', 0)} tool call(s)"
        )
        if event.get("tokens_in") is not None:
            label += f" · {event.get('tokens_in')} in / {event.get('tokens_out')} out"
        with st.expander(label, expanded=False):
            if event.get("content"):
                st.write(event["content"])
            st.json(event, expanded=False)
        return
    if event_type == "tool_call":
        name = event.get("name", "?")
        result = event.get("result") or {}
        is_error = "error" in result
        icon = "❌" if is_error else "🔧"
        elapsed = event.get("elapsed_ms")
        label = f"{icon} turn {turn} · {name}"
        if elapsed is not None:
            label += f" · {elapsed} ms"
        if is_error:
            label += f" · {result.get('code', 'error')}"
        with st.expander(label, expanded=False):
            st.caption("args")
            st.json(event.get("args") or {}, expanded=False)
            st.caption("result")
            st.json(result, expanded=False)
        return
    # Fallback for any event we didn't pattern-match.
    with st.expander(f"turn {turn} · {event_type}", expanded=False):
        st.json(event, expanded=False)


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------


dashboard_tab, log_tab = st.tabs(["Dashboard", "Agent Run Log"])

with dashboard_tab:
    _render_dashboard_tab()

with log_tab:
    _render_run_log_tab()
