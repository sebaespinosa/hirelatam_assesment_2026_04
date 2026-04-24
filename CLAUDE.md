# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

Solo 2-day take-home assessment for HireLatam. The plan lives in [PLAN.md](PLAN.md) (what to build and why) and [PHASES.md](PHASES.md) (how, in order); where code exists it is the source of truth and the plan docs are historical context.

**Phase progress:** P0 (scaffold) ✅, P1 (data model + persistence) ✅, P2 (launch classifier) ✅, P3 (Product Hunt ingestion) ✅, P4 (mock sources) ✅, P5 (ingestion orchestrator) ✅, P6 (enrichment orchestrator) ✅, P7 (DM draft orchestrator) ✅, P8 (dashboard) ✅, P9 (README + Loom script) ✅. [README.md](README.md) is the reviewer-facing entry point; [docs/loom_script.md](docs/loom_script.md) holds the 5-beat walkthrough script. `make demo` chains init-db + ingestion + enrichment + DM drafts for one-command reproduction. Classifier + eval: [src/classifier/](src/classifier/), [evals/run_classifier.py](evals/run_classifier.py). Sources: [src/sources/producthunt.py](src/sources/producthunt.py) (real), [src/sources/mocks.py](src/sources/mocks.py), [src/sources/mock_generator.py](src/sources/mock_generator.py). Agents: generic loop at [src/agent/orchestrator.py](src/agent/orchestrator.py); ingestion at [src/agent/tools.py](src/agent/tools.py) + [prompts/orchestrator.md](prompts/orchestrator.md) / [run_agent.py](run_agent.py); enrichment at [src/agent/enrichment_tools.py](src/agent/enrichment_tools.py) + [prompts/enrichment.md](prompts/enrichment.md) / [run_enrichment.py](run_enrichment.py); DM drafts at [src/agent/dm_tools.py](src/agent/dm_tools.py) + [src/agent/thresholds.py](src/agent/thresholds.py) + [prompts/dm_draft.md](prompts/dm_draft.md) / [run_dm_drafts.py](run_dm_drafts.py); turn-by-turn JSONL logs in `data/runs/`. Dashboard: [dashboard.py](dashboard.py) (Streamlit UI) backed by pure-Python query layer at [src/dashboard/queries.py](src/dashboard/queries.py) + run-log reader at [src/dashboard/run_log.py](src/dashboard/run_log.py).

Read [PLAN.md](PLAN.md) §5 (Data Source Decisions) and §7 (Deliberate Exclusions) before proposing changes — scope is intentionally narrow and several "obvious" improvements (FastAPI, Postgres, Docker, observability, real LinkedIn/X integration) have been explicitly ruled out for the timebox. Don't reintroduce them without discussion.

## Deliverable shape

A reviewer-facing demo with four moving parts, in order of importance:

1. **Agent orchestrator** (`src/agent/orchestrator.py`, Phase 5) — single Python script using the OpenAI Chat Completions API with function calling. One tool per data source + classifier + persistence + enrichment + DM draft. This is the AI-engineering centerpiece the reviewer is evaluating.
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
| Ingest all mocks | `make ingest-mocks` | `uv run python -m src.sources.mocks` |
| Regenerate mock seeds | `make generate-mocks` | `uv run python -m src.sources.mock_generator` |
| Run dashboard | `make dashboard` | `uv run streamlit run dashboard.py` |
| Run ingestion agent | `make run-agent` | `uv run python run_agent.py` |
| Run enrichment agent | `make run-enrichment` | `uv run python run_enrichment.py` |
| Run DM-draft agent | `make run-dm-drafts` | `uv run python run_dm_drafts.py` |
| Tests | `make test` | `uv run pytest` |
| Lint | `make lint` | `uv run ruff check .` |
| Format | `make fmt` | `uv run ruff format .` |

`python -m src.db.init` drops `data/db.sqlite` and replays [src/db/schema.sql](src/db/schema.sql). Pass `--keep` to apply idempotently, or `--db-path` to target a different file. The `data/db.sqlite` file is gitignored.

**Single test:** `uv run pytest path/to/test_file.py::test_name` or `uv run pytest -k <pattern>`.

Deps in [pyproject.toml](pyproject.toml): runtime — `openai`, `streamlit`, `pydantic`, `httpx`, `python-dotenv`; dev — `pytest`, `ruff`. No `sqlite-utils`; the DB layer will use the stdlib `sqlite3` module (Phase 1 decision — fewer deps, same ergonomics for this scope).

Ruff config in [pyproject.toml](pyproject.toml): line length 100, rule set `E,F,I,UP,B,SIM`, target `py311`.

## Scope discipline

The plan has explicit cut points ([PHASES.md §Contingency & Cut Points](PHASES.md)). If you find yourself behind, **cut bonuses (enrichment P6, DM draft P7) before cutting the classifier (P2) or the run-log viewer**. The North Star from the plan:

> A working demo of ingestion + classification + dashboard is a pass. Ingestion + classification + enrichment + DM + polished Loom is a hire signal. Don't trade the first for a shot at the second.

## Classifier eval set needs manual paste

[evals/launch_classifier.jsonl](evals/launch_classifier.jsonl) ships with 31 positive placeholders (`post_text: "[PASTE TEXT]"`) and 12 hand-crafted negatives. X blocks automated fetching and has no free API, so the positives require manual pasting from the browser — see [evals/README.md](evals/README.md) for the procedure. Until the positives are filled in, `python -m evals.run_classifier` only evaluates negatives; the `eval-classifier` target will silently skip placeholder entries with a "Skipped: N" line in the report. Do not fabricate post text — paste from the source URLs only.

`pos_016` has a known-malformed X URL (truncated status ID); either fix it or delete the entry before running the full eval.

## LLM provider

**OpenAI.** [PLAN.md](PLAN.md) and [PHASES.md](PHASES.md) were written targeting the Anthropic messages API with `tool_use`; the user swapped to OpenAI for credit reasons. The architecture pattern (forced structured output from an LLM call) is provider-neutral, but the docs still read "Anthropic" in places — treat that as historical framing, not a spec mismatch. If a future reviewer needs the Anthropic story, swapping back is a ~20-min reversal on one file ([src/classifier/classify.py](src/classifier/classify.py)) since the `ClassifierBackend` Protocol isolates provider details.

## Classifier invariants

- **Forced Structured Outputs, not free-form JSON.** [src/classifier/classify.py](src/classifier/classify.py) calls OpenAI Chat Completions with `response_format={"type": "json_schema", "json_schema": CLASSIFIER_OUTPUT_SCHEMA}` and `strict: true`. The entire response body is the classification — no tool-call wrapper, no JSON parsing from free text. Schema adherence is enforced by the API.
- **Automatic prompt caching.** OpenAI caches system prompts >1024 tokens automatically when the content is byte-identical across calls. No explicit flags. Consequence: **do not mutate the system prompt per-call** — any formatting drift breaks the cache.
- **Backend injection for tests.** `classify_launch(..., backend=StubBackend(response))` bypasses OpenAI entirely. No test should hit the network.
- **Cross-field invariant on `ClassificationResult`.** `launch_type` must be non-null iff `is_launch` is true — enforced by a Pydantic `@model_validator`. Don't relax this; the dashboard and DM-draft pass rely on it.
- **System prompt lives in markdown, not Python.** [src/classifier/prompt.py](src/classifier/prompt.py) loads [prompts/launch_classifier.md](prompts/launch_classifier.md) and strips the metadata header below `## System Prompt`. Never inline the prompt as a Python string.
- **Default model is `gpt-4o-mini`.** Classification is high-volume pattern-match; `gpt-4o-mini` is the cost-appropriate choice (also reliably available on any active OpenAI account). Override via `OpenAIBackend(model=...)` if accuracy regresses on the eval set.
- **Strict-mode schema caveat.** OpenAI `strict: true` ignores `minimum`/`maximum`/`minLength` constraints on JSON Schema primitives. Range/length validation happens in the Pydantic `ClassificationResult` after parsing — belt and suspenders, don't remove either layer.

## Orchestrator invariants

- **Three workflows share one loop.** `run_agent()` in [src/agent/orchestrator.py](src/agent/orchestrator.py) takes `tools`, `handlers`, `system_prompt`, and `tag` as params; ingestion (Phase 5), enrichment (Phase 6), and DM drafting (Phase 7) are three invocations with different tool sets. Do not fork the loop — add new workflows by passing a new tool bundle.
- **"Under-performing" is per-source, not global.** [src/agent/thresholds.py](src/agent/thresholds.py) groups launches by source before taking P25. A Product Hunt post with 300 votes might be low-for-PH while being high-for-LinkedIn. Default window is 60 days (not 30 — mock seeds span Feb–Apr 2026).
- **DM prompt is both style guide and orchestrator.** `prompts/dm_draft.md` pulls double duty — one system prompt runs the loop *and* dictates voice/length/anti-patterns. This is fine because the flow is trivial (list → draft+persist per launch → finish). Do not split into two prompts unless the flow gets more complex.
- **`prompt_version` is runtime-injected for DM drafts.** The agent doesn't pass it; `handle_persist_dm_draft` reads it from the prompt file. Bumping the prompt version = automatic audit trail on new drafts.
- **Enrichment is idempotent by construction.** `list_companies_missing_contacts` returns only companies without a contact row. A half-completed run plus a re-run covers any gap. Use this instead of explicit retry logic.
- **`find_*` tools are deterministic mocks** seeded by `hashlib.md5(company_name + field)`. Same company → same email/phone/LinkedIn/X handle across re-runs. Miss rates: email 15%, phone 30%, LinkedIn 5%, X 20% (verified empirically: 12/78, 23/78, 3/78, 17/78). Production swap: Hunter.io for email, Apollo.io for phone + LinkedIn, a paid X-API proxy for handles.
- **Agent routes, code writes.** The agent never emits SQL, never constructs a Pydantic model by name. It passes dicts to `persist_launch`/`persist_funding`/`persist_company`/`persist_contact` and the handlers validate + write. Phase 1 principle — don't weaken it.
- **Bundle-shaped persist calls.** `persist_launch({company, launch, classification})` upserts the company internally. The agent never needs to know a `company_id`. Same for `persist_funding({company, funding})`.
- **`persist_launch` refuses `is_launch=false` items.** Belt-and-suspenders enforcement of "classify before persist." If the policy check fires, it's almost always a prompt regression.
- **Every tool handler returns a dict; Pydantic failures surface as `{"error": ..., "code": "validation_error"}`.** The agent self-corrects once per item (per the prompt's retry rule), then skips. Handlers never raise into the orchestrator loop.
- **Turn-by-turn JSONL logs go to `data/runs/{timestamp}.jsonl`.** Events: `run_start`, `assistant`, `tool_call`, `finish`, `max_turns_reached`. The Phase 8 dashboard reads the latest file as its "Agent Run Log" tab — don't strip log lines to clean up noise; the log is a demo artifact.
- **Default orchestrator model is `gpt-4o`, not `gpt-4o-mini`.** Mini truncates parallel tool-call fan-out and silently skips entire sources on runs of this size (verified empirically: processes 19 of 55 social posts and hallucinates summary counts). `gpt-4o` follows the prompt's per-source sequencing reliably. Classifier stays on `gpt-4o-mini` — per-call, high volume, no multi-step reasoning needed. End-to-end run: ~4 min, ~141 tool calls, ~a few cents in OpenAI spend.
- **System prompt enforces per-source sequencing**, not a giant parallel fan-out. Turn 1 fetches all sources in parallel; subsequent turns process one source at a time. Parallelism is *within* each source only.
- **Agent's self-reported summary counts from tool results, not memory.** The prompt is explicit about this. Dashboard KPI tiles will eventually cross-check against `SELECT COUNT(*)`; until then, trust the JSONL log over the final summary text if they disagree.
- **Run-log viewer is non-negotiable.** It is what sells the AI-engineering story in the Loom walkthrough. Don't let dashboard scope creep remove it.

## Dashboard invariants

- **Streamlit imports no business logic.** [dashboard.py](dashboard.py) is UI only; all joins and aggregations live in [src/dashboard/queries.py](src/dashboard/queries.py) / [src/dashboard/run_log.py](src/dashboard/run_log.py) as pure functions. This keeps the query layer unit-testable without a Streamlit process.
- **`is_mock` is derived from `launch.source LIKE 'mock_%'` OR `funding_round.source LIKE 'mock_%'`.** Known edge: `mock_yc`-only companies (company rows with no launch and no funding) render *without* the MOCK badge because there's no row to probe. The batch label in their description (`"(YC W25)"`) is the visual signal instead. Fixing this would require adding an `origin_source` column to the `company` table — Phase 1 schema change, out of scope for the dashboard phase.
- **The dashboard does not shell out.** Phase 8's plan suggested a "Refresh agent" button that runs `run_agent.py`. Dropped deliberately — arbitrary shell execution from a browser-facing UI is a liability. Replaced with a sidebar caption listing the make targets the user can run in their terminal.
- **Connection cached via `@st.cache_resource`.** Queries are not cached (SQLite is fast; stale data in the dashboard is worse than an extra query).
- **Run-log selector shows up to 40 most recent runs.** The filename-embedded tag (`20260424T113749_dm_drafts.jsonl`) identifies which workflow produced the run. Untagged runs (ingestion from before the `tag` param was added) get `tag="ingestion"` by convention.

## Source adapter invariants

- **Every source ingest signature takes `conn`, `classify`, `persist`, `classify_fn`, and a source-specific input (`nodes` for PH, `source` for mocks).** The `classify_fn` parameter takes the Phase 2 `classify_launch` by default and accepts a fake for tests so no source-adapter test ever touches the real OpenAI client.
- **`normalize_*` functions are pure.** They return `(Company, Launch)`, `(Company, FundingRound)`, or `Company` with the company id as a `-1` placeholder; the ingest pipeline fills in the real id after `upsert_company`. Do not make the normalizer open a DB connection.
- **`raw_payload` stores the full un-normalized node plus any derived fields.** The classifier result goes in as `raw_payload["_classification"]` so rejection reasoning survives the filter without a schema change.
- **Snapshot fallback is per-source.** Each source that talks to a remote API saves its last successful response to `data/seed/<source>_snapshot.json` and falls back to it on any network failure. The `*_snapshot.json` glob is gitignored — treat them as local dev caches, not reviewer seed data.
- **Mock seed files are committed** (`data/seed/mock_*.json`, not `*_snapshot.json`). Regenerate via `make generate-mocks` when the schema changes or content looks stale.
- **Non-launches are skipped at ingest, not stored.** The Launch table is semantically for launches. The Phase 5 orchestrator's agent run log will preserve rejection reasoning; ingestion-time logging is stdout-only for now.
- **Classifier runs on social sources only.** X + LinkedIn mocks pass through `classify_launch`; Crunchbase (structured fundraise data) and YC (batch directory entries) skip it. If you add a new source, decide at the dispatch layer (don't make the classifier handle non-post inputs).
- **Dry-run mode (`--no-persist`) passes `conn=None` to `ingest`.** The function guards against `persist=True` with `conn=None` but happily dry-runs without a connection.
- **Every CLI main() calls `load_dotenv()` first.** `uv run` does not auto-load `.env`. New CLI entrypoints must call it before reading `OPENAI_API_KEY` / `PH_DEVELOPER_TOKEN`.

## Classifier metrics targets

From [docs/launch_definition.md](docs/launch_definition.md) §7. Enforced by [evals/run_classifier.py](evals/run_classifier.py) — it exits non-zero if any target is missed.

| Metric | Target | Why |
|---|---|---|
| Precision on positives | ≥ 0.90 | False positives pollute the dashboard and waste DM-draft budget |
| Recall on positives | ≥ 0.85 | Some miss is acceptable; low-confidence items can surface separately |
| Negative accuracy | ≥ 0.90 | Rejecting commentary / teasers / updates is the classifier's main value-add |

When a metric regresses: iterate on the few-shot examples in [prompts/launch_classifier.md](prompts/launch_classifier.md), not on the prose rules. Replace weak examples instead of appending — prompt length affects latency and cost per call at scale.
