# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

Solo 2-day take-home assessment for HireLatam. The plan lives in [PLAN.md](PLAN.md) (what to build and why) and [PHASES.md](PHASES.md) (how, in order); where code exists it is the source of truth and the plan docs are historical context.

**Phase progress:** P0 (scaffold) ✅ and P1 (data model + persistence) ✅ done. P2–P9 not started. `run_agent.py` is still a stub pointing to Phase 5; `dashboard.py` is still a Streamlit hello-world; the SQLite schema, Pydantic models, repo helpers, and init script are wired up with a round-trip test suite in `tests/`.

Read [PLAN.md](PLAN.md) §5 (Data Source Decisions) and §7 (Deliberate Exclusions) before proposing changes — scope is intentionally narrow and several "obvious" improvements (FastAPI, Postgres, Docker, observability, real LinkedIn/X integration) have been explicitly ruled out for the timebox. Don't reintroduce them without discussion.

## Deliverable shape

A reviewer-facing demo with four moving parts, in order of importance:

1. **Agent orchestrator** (`src/agent/orchestrator.py`, Phase 5) — single Python script using the Anthropic messages API with `tool_use`. One tool per data source + classifier + persistence + enrichment + DM draft. This is the AI-engineering centerpiece the reviewer is evaluating.
2. **Launch classifier** (`prompts/launch_classifier.md`, Phase 2) — prompt-based filter that turns the pipeline from "firehose ingester" into "intent-aware curator". Has a small eval set at `evals/launch_classifier.jsonl`. See [PHASES.md §Phase 2](PHASES.md).
3. **Streamlit dashboard** ([dashboard.py](dashboard.py), Phase 8 — currently a hello-world) — read-only UI over SQLite. Tabs: main dashboard + agent run log viewer (the run log viewer is what sells the AI-engineering story — don't drop it).
4. **README + Loom** (Phase 9) — tradeoff communication is part of the deliverable, not documentation of it.

## Architecture invariants

These are load-bearing decisions from the plan docs. Preserve them unless you're deliberately revising the plan.

- **Single agent script, not a service.** `run_agent.py` is a CLI entrypoint. Streamlit reads SQLite directly. Do not introduce a FastAPI/Flask layer.
- **SQLite with `source` + `raw_payload` columns on every ingested table.** Every row records its origin source and the untransformed payload for debugging. Enforce `UNIQUE(source, source_id)` on `launch` and `funding_round` so re-runs are idempotent.
- **Pydantic at the boundary, not raw dicts.** Tool schemas mirror Pydantic models. Agent tool outputs are validated; on validation failure, feed the error back as a tool result and let the agent self-correct once, then skip.
- **Code owns writes; agent owns routing.** The agent calls `persist_launch(Launch)` — it does not emit SQL. Don't give the agent a SQL-execution tool.
- **Mocks are explicitly labeled.** Every mocked row has `source: "mock"` and renders with a visible `[MOCK]` badge in the dashboard. Do not silently mix real and mocked data.
- **Prompts are versioned markdown under [prompts/](prompts/).** Do not inline prompts as Python string literals. The classifier, orchestrator system prompt, mock generator, and DM-draft prompt all live as committed files.
- **Agent turn logs written to `data/runs/{timestamp}.jsonl`.** The dashboard's "Agent Run Log" tab reads these. Don't strip the logging to clean up noise — the log is a demo artifact.
- **Cap the agent loop at N turns** during development to prevent runaway tool calls.

## Data sources — real vs. mocked

Decided in [PLAN.md §5](PLAN.md). Summary so you don't have to re-read it:

| Source | Status | Notes |
|---|---|---|
| Product Hunt | Real | Free GraphQL, `PH_DEVELOPER_TOKEN` in `.env`. Cache a snapshot at `data/seed/ph_snapshot.json` for offline demo fallback. |
| Hacker News (Algolia) | Real, secondary | Zero-auth REST. Cut first if time runs short. |
| YCombinator | Best-effort scrape of `ycombinator.com/companies`; otherwise mocked. |
| X / Twitter | Mocked | Paid-only as of Feb 2026; ToS-safe scraping is not feasible. |
| LinkedIn | Mocked | No public API; *hiQ v. LinkedIn* ongoing. |
| Crunchbase | Mocked | Free tier too gated for this exercise. |
| Google funding announcements | Mocked | No canonical source. |

Mocks are **generated once** via a Claude prompt ([prompts/mock_generator.md](prompts/mock_generator.md), planned) and saved to `data/seed/*.json`. Do not regenerate per-run.

## Layout

Scaffolded in Phase 0. Subpackages exist as empty `__init__.py` modules — populate them in the phase noted.

```
run_agent.py            # agent CLI entrypoint (stub — Phase 5)
dashboard.py            # streamlit entry (hello-world — Phase 8)
src/
  agent/                # orchestrator + tool defs + thresholds (Phase 5/7)
  sources/              # one module per source: producthunt, hn, mock_x, ... (Phase 3/4)
  models/               # pydantic schemas (Phase 1)
  db/                   # schema.sql, repo.py, init script (Phase 1)
  classifier/           # launch classifier wrapper (Phase 2)
prompts/                # versioned .md prompts (Phase 2/4/5/7)
evals/                  # jsonl eval sets (Phase 2)
data/
  seed/                 # mock JSON seed files (committed, Phase 4)
  runs/                 # agent turn logs (gitignored, Phase 5)
  db.sqlite             # gitignored (Phase 1)
docs/                   # launch_definition.md, etc. (Phase 2)
```

## Commands

Tooling is `uv` with Python ≥ 3.11. `uv.lock` is committed for reviewer reproducibility. `[tool.uv] package = false` in [pyproject.toml](pyproject.toml) — this is an application, not a library; nothing gets installed from `src/`, so module invocation works via the uv-managed venv's `sys.path`.

| Task | Make target | Direct uv |
|---|---|---|
| Install deps | `make install` | `uv sync` |
| Init / reset DB | `make init-db` | `uv run python -m src.db.init` |
| Run dashboard | `make dashboard` | `uv run streamlit run dashboard.py` |
| Run agent | `make run-agent` | `uv run python run_agent.py` |
| Tests | `make test` | `uv run pytest` |
| Lint | `make lint` | `uv run ruff check .` |
| Format | `make fmt` | `uv run ruff format .` |

`python -m src.db.init` drops `data/db.sqlite` and replays [src/db/schema.sql](src/db/schema.sql). Pass `--keep` to apply idempotently, or `--db-path` to target a different file. The `data/db.sqlite` file is gitignored.

**Single test:** `uv run pytest path/to/test_file.py::test_name` or `uv run pytest -k <pattern>`.

Deps in [pyproject.toml](pyproject.toml): runtime — `anthropic`, `streamlit`, `pydantic`, `httpx`, `python-dotenv`; dev — `pytest`, `ruff`. No `sqlite-utils`; the DB layer will use the stdlib `sqlite3` module (Phase 1 decision — fewer deps, same ergonomics for this scope).

Ruff config in [pyproject.toml](pyproject.toml): line length 100, rule set `E,F,I,UP,B,SIM`, target `py311`.

## Scope discipline

The plan has explicit cut points ([PHASES.md §Contingency & Cut Points](PHASES.md)). If you find yourself behind, **cut bonuses (enrichment P6, DM draft P7) before cutting the classifier (P2) or the run-log viewer**. The North Star from the plan:

> A working demo of ingestion + classification + dashboard is a pass. Ingestion + classification + enrichment + DM + polished Loom is a hire signal. Don't trade the first for a shot at the second.

## Phase 2 needs user input

The launch classifier is grounded in reference X posts the user plans to provide. Without them, the classifier falls back to a generic definition — still works, but loses the "grounded in real examples" angle. If you're about to implement Phase 2 and haven't seen reference posts in the conversation, ask before writing the definition.
