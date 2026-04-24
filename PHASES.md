# Phased Implementation Plan

Companion to `PLAN.md`. That document captured *what* to build and *why*; this one captures *how* to build it, in the order that keeps the demo reachable at every checkpoint.

## Phase Dependency Graph

```
  ┌─────────────────┐
  │ P0: Setup       │
  └────────┬────────┘
           │
  ┌────────▼────────┐      ┌──────────────────────┐
  │ P1: Data Model  │      │ P2: Launch Definition │
  └────────┬────────┘      │     & Classifier      │
           │               └──────────┬───────────┘
           │                          │
           ├─────────────┬────────────┤
           ▼             ▼            ▼
    ┌──────────┐  ┌────────────┐  ┌──────────┐
    │ P3: PH   │  │ P4: Mock   │  │ (informs │
    │ ingest   │  │ seed gen   │  │  P3, P4, │
    └────┬─────┘  └─────┬──────┘  │  P5)     │
         │              │          └──────────┘
         └──────┬───────┘
                ▼
       ┌─────────────────┐
       │ P5: Agent       │  ◄── critical path ends here for MVP
       │     Orchestr.   │
       └────────┬────────┘
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
 ┌───────┐ ┌────────┐ ┌──────────┐
 │ P6:   │ │ P7:    │ │ P8:      │
 │ Enrich│ │ DM     │ │ Dashboard│
 │ (bonus)│ │ (bonus)│ └────┬─────┘
 └───┬───┘ └────┬───┘       │
     └─────┬────┘           │
           └────────┬───────┘
                    ▼
            ┌───────────────┐
            │ P9: README +  │
            │    Loom       │
            └───────────────┘
```

**Critical path to a demoable MVP:** P0 → P1 → P2 → P3 → P5 → P8 → P9 (~7 hours).
**Bonuses (P6, P7) and mock breadth (P4) layer on top** — cut first if running behind.

---

## Phase 0 — Setup & Scaffolding

**Time:** 30 min
**Prerequisites:** None

**Goal.** A runnable repo skeleton with env handling, dependency management, and a Streamlit "hello world" that launches.

**Tasks:**
1. `pyproject.toml` with `uv` or `poetry`. Deps: `anthropic`, `streamlit`, `pydantic`, `httpx`, `sqlite-utils` (or raw `sqlite3`), `python-dotenv`.
2. Directory layout:
   ```
   /
     run_agent.py            # entrypoint
     dashboard.py            # streamlit entry
     src/
       agent/                # orchestrator + tool defs
       sources/              # one module per source
       models/               # pydantic schemas
       db/                   # sqlite helpers, schema.sql
       classifier/           # launch classifier
     prompts/                # versioned .md prompts
     evals/                  # jsonl eval sets
     data/
       seed/                 # mock JSON seed files
       db.sqlite             # gitignored
     docs/                   # launch_definition.md, etc.
     PLAN.md
     PHASES.md
     README.md
   ```
3. `.env.example` with `ANTHROPIC_API_KEY`, `PH_DEVELOPER_TOKEN` (Product Hunt).
4. `.gitignore`: `.env`, `data/db.sqlite`, `__pycache__`, `.venv`.
5. `make run-agent` and `make dashboard` targets, or equivalent `uv run` scripts.

**Output:** Empty but runnable `streamlit run dashboard.py` showing a title.
**Done when:** `uv sync && streamlit run dashboard.py` works on a fresh clone.

---

## Phase 1 — Data Model & Persistence

**Time:** 1 hour
**Prerequisites:** P0

**Goal.** SQLite schema and Pydantic models that the rest of the pipeline writes to and reads from.

**Tasks:**
1. Define Pydantic models in `src/models/`:
   - `Company(id, name, website, description, created_at)`
   - `Launch(id, company_id, source, source_id, title, url, posted_at, engagement_score, engagement_breakdown: dict, raw_payload: dict)`
   - `FundingRound(id, company_id, source, amount_usd, round_type, announced_at, investors: list, raw_payload: dict)`
   - `Contact(id, company_id, email, phone, linkedin_url, x_handle, confidence, source)`
   - `DmDraft(id, launch_id, subject, body, tone, generated_at, prompt_version)`
2. `src/db/schema.sql` matching the models. Use TEXT for JSON columns, cast on read.
3. `src/db/repo.py` with `upsert_company`, `insert_launch`, `insert_funding`, `insert_contact`, `insert_dm_draft`, and a handful of read helpers.
4. Init script: `python -m src.db.init` drops and recreates the DB from schema.

**Output:** Typed persistence layer. Nothing hits the DB yet, but anything can.
**Done when:** Round-trip test: `upsert_company → fetch → pydantic validates` passes.

**Gotchas:**
- Enforce `UNIQUE(source, source_id)` on `Launch` and `FundingRound` to make re-runs idempotent.
- Store `raw_payload` even for mocks — keeps the debugging story honest.

---

## Phase 2 — Launch Definition & Classifier ⚠️ *Needs user input*

**Time:** 1 hour
**Prerequisites:** P0. Requires the reference X posts you mentioned.

**Goal.** A written definition of what counts as a "launch" + a prompt-based classifier that the orchestrator can call as a filter. This phase is what turns the agent from "firehose ingester" into "intent-aware curator" — and it's the single highest-value demo moment.

**Tasks:**
1. Analyze the reference X posts. Extract recurring features:
   - Is it first-person from founder/company account?
   - Does it announce a *new* product, feature, or milestone vs. an update?
   - Does it link to a product page, demo, or app store?
   - Is the language launch-flavored ("today we're launching", "introducing", "excited to announce", "now live")?
   - Is there media (video, screenshot, hero image)?
2. Write `docs/launch_definition.md`: prose definition + criteria checklist + edge cases (soft launches, waitlists, relaunches, fundraise tweets that *mention* a product).
3. Build `prompts/launch_classifier.md`:
   - System prompt grounded in the definition.
   - 4–6 few-shot examples drawn from the reference posts (positive).
   - 4–6 negative examples (product updates, memes, retweets, plain marketing, company news without a launch).
   - Output schema: `{is_launch: bool, confidence: 0.0-1.0, reasoning: str, launch_type: "product"|"feature"|"milestone"|null}`.
4. Build `evals/launch_classifier.jsonl`: the reference posts + ~10 hand-labeled negatives. Include a small script that runs the classifier over the eval set and prints precision/recall. Doesn't need to be rigorous — even 20 examples is enough to prove the methodology.
5. Expose as a tool `classify_launch(post_text: str, metadata: dict) -> ClassificationResult` usable by the main agent.

**Output:** A reusable classifier that the ingestion pipelines (P3, P4) filter through before writing to DB.
**Done when:** Classifier correctly labels ≥ 80% of the eval set. Reference posts all come back as `is_launch=true`.

**Why this deserves its own phase:** "I have an eval set and a versioned prompt" is a differentiator for an AI-engineering role. Most assessments ship a single uncommented prompt inline. This phase costs an hour and converts that into demonstrable prompt-engineering discipline.

---

## Phase 3 — Product Hunt Integration

**Time:** 1.5 hours
**Prerequisites:** P1, P2

**Goal.** Real, live ingestion from Product Hunt, classified through the launch filter, written to SQLite.

**Tasks:**
1. Register a Product Hunt developer app, obtain a developer token, add to `.env`.
2. Build `src/sources/producthunt.py`:
   - GraphQL query for recent posts: `id, name, tagline, url, votesCount, commentsCount, createdAt, makers, topics, media`.
   - Normalizer mapping PH response → `Launch` + `Company` Pydantic models.
   - Retry on 429 with backoff; degrade to cached response on failure (keep a `data/seed/ph_snapshot.json` for offline demo).
3. Wire PH fetch → launch classifier → DB insert. Skip non-launches or flag with `launch_type=null`.
4. CLI: `python -m src.sources.producthunt --days 7` pulls + persists.

**Output:** Real Product Hunt launches in SQLite, filtered.
**Done when:** Fresh DB + CLI run produces ≥ 20 launches, all visible to `SELECT * FROM launch`.

**Gotchas:**
- PH's GraphQL rate limit is generous but real. Paginate properly.
- `votesCount` is a reasonable engagement_score proxy; store both it and `commentsCount` in `engagement_breakdown`.

---

## Phase 4 — Mock Source Generation

**Time:** 1 hour
**Prerequisites:** P1, P2

**Goal.** Realistic-looking mocked data for X, LinkedIn, Crunchbase, YC, styled after the launch definition from P2.

**Tasks:**
1. Write `prompts/mock_generator.md` that takes the launch definition + reference examples as input and generates:
   - ~20 X launch posts (post text, likes, reposts, posted_at)
   - ~15 LinkedIn launch posts (post text, reactions, comments)
   - ~30 Crunchbase-style fundraise records (company, amount, round, investors, date)
   - ~15 YC W/S-batch companies (name, description, batch, website)
2. Run the generator once, save outputs to `data/seed/{source}.json`. Generation is one-shot, not per-run.
3. Loader functions per source that read the JSON and emit Pydantic objects with `source="mock"` stamped on every row.
4. Every dashboard row that came from a mock source gets a visible `[MOCK]` badge (handled in P8).

**Output:** `data/seed/*.json` + loader modules.
**Done when:** A fresh DB run ingests ~80 mocked rows that look plausible alongside real PH data.

**Cut strategy:** if behind, ship only mock-X and mock-Crunchbase. Skip LinkedIn and YC.

---

## Phase 5 — Agent Orchestrator

**Time:** 2 hours
**Prerequisites:** P1, P2, P3, P4

**Goal.** The single script that ties everything together via `tool_use`. This is the AI-engineering centerpiece.

**Tasks:**
1. `src/agent/tools.py`: tool definitions for
   - `fetch_producthunt(days: int)`
   - `load_mock_source(source: Literal["x","linkedin","crunchbase","yc"])`
   - `classify_launch(post_text, metadata)` — from P2
   - `persist_launch(launch: Launch)`
   - `persist_funding(round: FundingRound)`
   Each with a strict JSON schema matching the Pydantic model.
2. `src/agent/orchestrator.py`: main loop using Anthropic messages API. System prompt instructs the agent to:
   - Call each source tool once
   - Pipe each post through `classify_launch` before persisting
   - Report a summary at the end (counts per source, classification stats)
3. On Pydantic validation failure: feed the validation error back into the next turn as a tool result, let the agent self-correct once. If it fails twice, log and skip.
4. Versioned system prompt at `prompts/orchestrator.md`.
5. Log every agent turn (tool name, input, output, tokens) to `data/runs/{timestamp}.jsonl` for the README walkthrough.

**Output:** `python run_agent.py` pulls PH + mocks, classifies, persists, logs.
**Done when:** End-to-end run populates the DB from empty in under 2 minutes and the JSONL log is readable.

**Gotchas:**
- Don't let the agent *write* the persistence SQL — it calls `persist_launch(pydantic_object)`. Agent owns routing; code owns writes.
- Cap the agent loop at N turns to prevent runaway tool calls during development.

---

## Phase 6 — Enrichment Pass (Bonus)

**Time:** 1 hour
**Prerequisites:** P5

**Goal.** Second agent pass that populates the `contact` table per company.

**Tasks:**
1. Tools: `find_email(company)`, `find_phone(company)`, `find_linkedin(company)`, `find_x_handle(company)`. All return `(value, confidence, source)`. All mocked — return plausible synthetic data (`ceo@acmecorp.com`, `linkedin.com/company/acmecorp`) with a confidence score.
2. Second orchestrator script `run_enrichment.py` that iterates over companies missing contacts and calls the agent.
3. Persist to `contact`. README notes: *"Production swap: Hunter.io for emails, Apollo.io for phones + LinkedIn. Free tiers cover prototype volume."*

**Output:** Populated `contact` table.
**Done when:** Every company in the DB has at least one contact row.

**Cut it if:** behind by end of hour 5. The dashboard can just show a greyed-out "enrichment not run" state.

---

## Phase 7 — DM Draft Pass (Bonus)

**Time:** 1 hour
**Prerequisites:** P5 (P6 optional but better together)

**Goal.** Third agent pass drafting outbound DMs for poorly-performing launches.

**Tasks:**
1. Define "poorly performing" concretely. Suggested heuristic: `engagement_score < P25 of launches from the same source in the last 30 days`. Store the threshold logic in `src/agent/thresholds.py` so it's reviewable.
2. `prompts/dm_draft.md`: system prompt covers tone (warm, specific, non-salesy), structure (hook referencing their launch + offer + soft CTA), length (≤ 80 words), anti-patterns (no "I noticed your launch underperformed" — the whole point is to not lead with the negative).
3. Tool: `draft_dm(launch, company, contact) -> DmDraft`. Agent calls once per qualifying launch.
4. Persist to `dm_draft` table. Show in dashboard per-launch expander (P8).

**Output:** Drafts ready to show in the UI.
**Done when:** At least 5 drafts in the DB, each referencing the actual launch they're targeting.

**Demo note:** this is the single best "wow" moment — a reviewer sees a real-looking launch, a low engagement score, and a thoughtful outreach draft. Make sure one of the drafts is polished enough to read aloud in the Loom.

---

## Phase 8 — Dashboard

**Time:** 1.5 hours
**Prerequisites:** P5 (P6, P7 optional)

**Goal.** A Streamlit UI that a reviewer can click through without reading any code.

**Layout:**
- **Sidebar:** source filter (multi-select), date range, engagement threshold slider, "Refresh agent" button (shells out to `run_agent.py`).
- **Top row — 4 KPI tiles:** Total companies tracked / Total raised (sum of funding rounds, USD) / Avg engagement per launch / # launches flagged for outreach.
- **Main table:** one row per company. Columns: name, [MOCK] badge if applicable, latest launch title, engagement score, total raised, last funding round, has contacts?, has DM draft?
- **Per-row expander:** full launch details, funding history, enriched contacts (emails + phones + LinkedIn + X), DM draft with a "copy to clipboard" button.
- **Secondary tab:** agent run log viewer — reads the latest `data/runs/*.jsonl` and shows turn-by-turn tool calls. This is what sells the AI-engineering story.

**Tasks:**
1. Scaffold with `st.tabs` for "Dashboard" / "Agent Run Log".
2. Query helpers in `src/db/repo.py` for the join-heavy dashboard queries.
3. Chart: bar chart of total raised per company (top 10). Keep visuals minimal — one chart, not five.
4. Mock badges: `st.badge` or styled span, clear visual distinction from real data.

**Done when:** Loom-ready. A reviewer with no context can look at it and understand what happened.

---

## Phase 9 — README + Loom

**Time:** 1 hour
**Prerequisites:** P8

**README sections (in order):**
1. **What this is** — two sentences.
2. **Demo** — embedded Loom link or GIF, followed by `make demo` instructions.
3. **Architecture** — the ASCII diagram from PLAN.md + one paragraph.
4. **What's real, what's mocked** — table. Transparency upfront.
5. **The AI-engineering parts** — launch classifier, orchestrator, enrichment, DM draft. Links to the `prompts/` directory.
6. **Scope decisions** — link to PLAN.md §7 ("Deliberate Exclusions").
7. **What I'd do with another week** — short, honest list: real X via TwitterAPI.io, real LinkedIn via Proxycurl, observability via OpenTelemetry, move off Streamlit to a proper backend + frontend split.
8. **How to run** — `uv sync && cp .env.example .env && python run_agent.py && streamlit run dashboard.py`.

**Loom script (3–5 min):**
1. 30s — the problem and the scope decision (mocks vs. real)
2. 90s — live demo of the dashboard
3. 60s — show the orchestrator code + a prompt file + the eval set
4. 30s — one DM draft read aloud
5. 30s — what a production version would look like

**Done when:** README renders cleanly in GitHub preview, Loom uploaded, link in README.

---

## Contingency & Cut Points

| If at end of… | And you're behind on… | Then… |
|---|---|---|
| Hour 4 | P5 not started | Drop P4 to only X + Crunchbase mocks; skip YC and LinkedIn |
| Hour 6 | P5 still shaky | Cut P6 and P7 entirely; dashboard shows ingestion only |
| Hour 8 | P6/P7 half-done | Ship whichever is further along; README notes the other as "designed, not merged" |
| Hour 10 | Loom not recorded | README + screenshots only; Loom becomes optional follow-up |

The North Star: **a working demo of ingestion + classification + dashboard** is a pass. **Ingestion + classification + enrichment + DM + polished Loom** is a hire signal. Don't trade the first for a shot at the second.

---

## Inputs Needed Before Starting

1. **The X posts you mentioned** — links or text. These power Phase 2 (definition + few-shot examples + eval set) and Phase 4 (mock realism). Without them, Phase 2 falls back to a generic launch definition, which works but loses the "grounded in real examples" angle.
2. **Any prior Anthropic API key / rate-limit constraints** — affects whether the orchestrator can run freely or needs aggressive caching.
3. **Preferred Python tooling** — `uv` vs `poetry` vs plain venv. Defaults to `uv` in this plan.
