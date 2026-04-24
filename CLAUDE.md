# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

Solo 2-day take-home assessment for HireLatam. The plan lives in [PLAN.md](PLAN.md) (what to build and why) and [PHASES.md](PHASES.md) (how, in order); where code exists it is the source of truth and the plan docs are historical context.

**Phase progress:** P0 (scaffold) ✅, P1 (data model + persistence) ✅, P2 (launch classifier) ✅, P3 (Product Hunt ingestion) ✅. P4–P9 not started. `run_agent.py` is still a stub pointing to Phase 5; `dashboard.py` is still a Streamlit hello-world. The launch definition lives at [docs/launch_definition.md](docs/launch_definition.md); the versioned system prompt at [prompts/launch_classifier.md](prompts/launch_classifier.md); the classifier backend in [src/classifier/](src/classifier/); eval runner at [evals/run_classifier.py](evals/run_classifier.py); Product Hunt source at [src/sources/producthunt.py](src/sources/producthunt.py) (CLI: `make ingest-ph`).

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
| Run classifier eval | `make eval-classifier` | `uv run python -m evals.run_classifier` |
| Ingest Product Hunt | `make ingest-ph` | `uv run python -m src.sources.producthunt` |
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

## Classifier eval set needs manual paste

[evals/launch_classifier.jsonl](evals/launch_classifier.jsonl) ships with 31 positive placeholders (`post_text: "[PASTE TEXT]"`) and 12 hand-crafted negatives. X blocks automated fetching and has no free API, so the positives require manual pasting from the browser — see [evals/README.md](evals/README.md) for the procedure. Until the positives are filled in, `python -m evals.run_classifier` only evaluates negatives; the `eval-classifier` target will silently skip placeholder entries with a "Skipped: N" line in the report. Do not fabricate post text — paste from the source URLs only.

`pos_016` has a known-malformed X URL (truncated status ID); either fix it or delete the entry before running the full eval.

## Classifier invariants

- **Forced tool use, not free-form JSON.** [src/classifier/classify.py](src/classifier/classify.py) calls Anthropic with `tool_choice={"type": "tool", "name": "record_classification"}` so the model can only respond via the tool. Schema adherence is enforced by the API rather than parsed after the fact.
- **Prompt caching on the system block.** The system prompt is sent with `cache_control: {"type": "ephemeral"}`. 40+ calls in a single eval run share one cache entry.
- **Backend injection for tests.** `classify_launch(..., backend=StubBackend(response))` bypasses Anthropic entirely. No test should hit the network.
- **Cross-field invariant on `ClassificationResult`.** `launch_type` must be non-null iff `is_launch` is true — enforced by a Pydantic `@model_validator`. Don't relax this; the dashboard and DM-draft pass rely on it.
- **System prompt lives in markdown, not Python.** [src/classifier/prompt.py](src/classifier/prompt.py) loads [prompts/launch_classifier.md](prompts/launch_classifier.md) and strips the metadata header below `## System Prompt`. Never inline the prompt as a Python string.
- **Default model is `claude-haiku-4-5`.** Classification is high-volume pattern-match; Haiku is the cost-appropriate choice. Override via `AnthropicBackend(model=...)` if accuracy regresses on the eval set.

## Source adapter invariants

- **Every source module exposes `ingest(*, conn, nodes, classify, persist, classify_fn)`.** The `classify_fn` parameter takes the Phase 2 `classify_launch` by default and accepts a fake for tests so no source-adapter test ever touches the real Anthropic client.
- **`normalize_post`-style functions are pure.** They return `(Company, Launch)` with `launch.company_id = -1` as a placeholder; the ingest pipeline fills in the real id after `upsert_company`. Do not make the normalizer open a DB connection.
- **`raw_payload` stores the full un-normalized node plus any derived fields.** The classifier result goes in as `raw_payload["_classification"]` so rejection reasoning survives the filter without a schema change.
- **Snapshot fallback is per-source.** Each source that talks to a remote API saves its last successful response to `data/seed/<source>_snapshot.json` and falls back to it on any network failure. Snapshots are gitignored — treat them as local dev caches, not reviewer seed data.
- **Non-launches are skipped at ingest, not stored.** The Launch table is semantically for launches. The Phase 5 orchestrator's agent run log will preserve rejection reasoning; ingestion-time logging is stdout-only for now.
- **Dry-run mode (`--no-persist`) passes `conn=None` to `ingest`.** The function guards against `persist=True` with `conn=None` but happily dry-runs without a connection.

## Classifier metrics targets

From [docs/launch_definition.md](docs/launch_definition.md) §7. Enforced by [evals/run_classifier.py](evals/run_classifier.py) — it exits non-zero if any target is missed.

| Metric | Target | Why |
|---|---|---|
| Precision on positives | ≥ 0.90 | False positives pollute the dashboard and waste DM-draft budget |
| Recall on positives | ≥ 0.85 | Some miss is acceptable; low-confidence items can surface separately |
| Negative accuracy | ≥ 0.90 | Rejecting commentary / teasers / updates is the classifier's main value-add |

When a metric regresses: iterate on the few-shot examples in [prompts/launch_classifier.md](prompts/launch_classifier.md), not on the prose rules. Replace weak examples instead of appending — prompt length affects latency and cost per call at scale.
