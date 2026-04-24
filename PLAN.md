# Working Plan — Launch & Fundraise Intelligence Dashboard

## 1. Context

The assessment asks for a dashboard that aggregates launch videos from X and LinkedIn, fundraise announcements from Crunchbase / Google / YCombinator, plots capital raised and launch engagement per company, and (as bonuses) surfaces enriched contact methods and drafts outbound DMs to poorly-performing launches.

This is a realistic *product* scope, not a realistic *2-day* scope. The plan below narrows aggressively to what a single engineer can ship well in the timebox, while making the scope decisions explicit so the reviewer can evaluate the **engineering judgment** alongside the code.

## 2. Goals (what the deliverable must prove)

1. Ability to design and ship an **agent-driven pipeline** with structured outputs and multiple tool calls — this is the AI-engineering core of the role.
2. Ability to **ingest, normalize, and persist** data from heterogeneous sources into a unified model.
3. Ability to chain LLM operations for enrichment and generation (contact lookup + DM drafting).
4. A working dashboard the reviewer can click through end-to-end.
5. Clear communication of scope tradeoffs in README and commit messages — evidence of senior judgment, not just execution.

## 3. Non-Goals (deliberately out of scope; see §7 for rationale)

- Multi-tenant auth, user accounts, SSO
- A dedicated backend service separate from the dashboard
- Production observability (structured logging, OpenTelemetry tracing, metrics, dashboards, alerting)
- CI/CD, Docker, IaC, cloud deployment
- Exhaustive test coverage — only critical-path tests for the agent layer
- Database migrations, connection pooling, caching, queueing
- Rate-limit handling, retry/backoff beyond basic, circuit breakers
- Secret management beyond `.env`
- i18n, accessibility audit, responsive design polish

## 4. Constraints

| Constraint | Implication |
|---|---|
| ~2 business days, part-time attention (≈ 8–12 working hours) | Every integration must justify its hours |
| Solo engineer | No parallelization; pick sequential work that unblocks demo fast |
| No paid API budget assumed | Free or nominal-cost sources only |
| Demo-driven review | Offline-reproducible demo > live API calls that might fail during review |

## 5. Data Source Decisions

The assessment lists X, LinkedIn, Crunchbase, Google, and YC. Each was evaluated on auth friction, cost, legal/ToS risk, and time-to-first-byte. Summary:

| Source | Decision | Reasoning |
|---|---|---|
| **Product Hunt** | ✅ **Real integration** | Free GraphQL API, no OAuth, upvotes + comment counts are a direct analogue for "launch engagement". Time-to-first-byte ≈ 15 min. |
| **Hacker News (Algolia)** | ✅ **Real integration (secondary)** | Zero-auth REST API; Show HN posts capture indie/dev launches that often precede PH. Free. |
| **X (Twitter)** | ❌ **Mocked** | X moved to pay-per-use billing in Feb 2026 with no free read tier for new developer accounts. Community MCPs exist (EnesCinr, Dishant27, mbelinky, crazyrabbitLTC) but all wrap the paid API. Twikit-based MCPs (adhikasp, lord-dubious) auth via username/password — against ToS and demo-fragile. Third-party proxies (TwitterAPI.io, GetXAPI) are viable but still require credit setup. Not worth the hours for a demo. |
| **LinkedIn** | ❌ **Mocked** | No public API for post engagement. Scraping is actively litigated (*hiQ v. LinkedIn*, ongoing). Any real integration here would be 1–2 days alone. |
| **Crunchbase** | ❌ **Mocked** | Free tier is gated and limited. Their paid API is the serious path. |
| **YCombinator** | ⚠️ **Best-effort real** | Public companies directory is scrape-able (`ycombinator.com/companies`). Will attempt if time remains; otherwise mocked. |
| **Google funding announcements** | ❌ **Mocked** | Vague source; no canonical API. Would realistically be a web search + extraction agent — interesting but too open-ended for the timebox. |

**Mock strategy.** Mocks are not hand-written stubs. A Claude prompt generates ~40 realistic fundraise records and ~20 X/LinkedIn launch records as a JSON seed file (company, round, amount, date, investors, post copy, engagement counts). Every mocked row is flagged with a `source: "mock"` field and rendered with a visible badge in the dashboard. The ingestion interface is source-agnostic — swapping a mock loader for a real API client is ≤ 20 LOC per source.

**Why transparency over a convincing fake.** A reviewer who spots undisclosed mock data loses trust in the whole deliverable. A reviewer who sees *explicitly-labeled* mocks alongside a clean source-adapter interface reads it as scope discipline. Same hours, very different signal.

## 6. Architecture

```
┌────────────────────┐
│  run_agent.py      │   Scheduled / manual trigger
│  (agent orchestr.) │
└────────┬───────────┘
         │ tool_use
  ┌──────┼──────┬──────────┬───────────┐
  ▼      ▼      ▼          ▼           ▼
 PH    HN Algolia  mock_x   mock_li   mock_cb
 tool    tool      loader   loader    loader
  │      │          │         │          │
  └──────┴────┬─────┴─────────┴──────────┘
             ▼
      Pydantic models
             ▼
         SQLite
             ▼
   ┌─────────────────┐
   │ Streamlit app   │
   │ (read-only UI)  │
   └─────────────────┘
```

**Components:**

- **Agent orchestrator** — single Python script. Uses Anthropic messages API with `tool_use`. One tool per data source + enrichment + DM-draft tools. System prompt and per-tool schemas defined in `prompts/` as versioned markdown.
- **Persistence** — SQLite, single file. Tables: `company`, `launch`, `funding_round`, `contact`, `dm_draft`. Each table has a `source` and `raw_payload` JSON column (same pattern as a `sync_summary` JSONB approach on Postgres — preserves source fidelity for debugging).
- **Dashboard** — Streamlit, single file. Reads SQLite directly. Sortable table of companies with joined funding + engagement, filter controls (source, date range, round size), per-row expander showing enriched contacts and draft DM.
- **Enrichment step** — second agent pass, per row. Tools: `find_email`, `find_phone`, `find_linkedin`, `find_x_handle`. Real calls mocked for this exercise (Hunter.io / Apollo.io free tiers would be the production swap).
- **DM-draft step** — triggered on rows where `engagement_score < threshold`. One prompt, tone-aware, returns structured draft (subject, body, signoff).

**Why Streamlit + SQLite and not FastAPI + Postgres:** FastAPI + Postgres is the architecture I would ship to production — and exactly the wrong choice for a 2-day demo. Streamlit removes an entire frontend stack and gives tables, charts, buttons, and a passable UI for free. SQLite removes Docker, migrations, connection strings, and a running service. The agent layer is what's being evaluated; everything else should be the shortest path to a clickable demo.

## 7. Deliberate Exclusions — What a Production Version Would Add

These are called out in the README so the reviewer sees them as conscious tradeoffs, not oversights.

- **Dedicated backend service.** Production would separate the agent worker from the dashboard (FastAPI + a Cloud Run job triggered by Cloud Scheduler, same pattern as production telemetry pipelines I've shipped). Here, a single Python script is a script.
- **Authentication & authorization.** No login, no RBAC. Production would add SSO + row-level permissions scoped to sales territory.
- **Observability.** No structured logging, no OpenTelemetry, no metrics. Production would add per-agent-call tracing, prompt/response logging, token-usage metrics, and an alerting policy on failure rate.
- **CI/CD & deployment.** Runs locally. Production would add GitHub Actions, containerization, and deploy to Cloud Run.
- **Rate limits, retries, backoff.** Minimal. Production would wrap every tool call in a retry decorator with exponential backoff and dead-letter logging.
- **Secret management.** `.env` file. Production would use Secret Manager.
- **Testing.** Only the agent's structured-output parsing and the DM-draft prompt have tests. No integration tests, no E2E, no load testing.
- **Source adapter hardening.** Product Hunt schema changes, HN rate limits, and scraper brittleness are all unhandled. Production would add schema contracts and a canary job.
- **Caching.** Every agent run hits sources fresh. Production would add a fingerprint-based dedup layer (id → content hash) to skip unchanged records.

Each of these is a real day of work minimum. Spending any of them in the 2-day window trades visibly-working AI features for invisibly-correct infrastructure. Wrong call for this assessment.

## 8. Implementation Plan

| Hour | Task |
|---|---|
| 1 | Repo scaffold, `pyproject.toml`, `.env.example`, Streamlit hello-world, SQLite schema + init script |
| 2 | Mock seed data generation (one Claude prompt producing JSON), loader functions for mocked sources |
| 3 | Product Hunt tool: GraphQL query, Pydantic response model, agent tool definition |
| 4 | Agent orchestrator: messages API loop with `tool_use`, structured writes to SQLite |
| 5 | Hacker News tool (if time); otherwise extra polish on PH |
| 6 | Enrichment agent pass: 4 tools (email, phone, LinkedIn, X), mocked backends, persisted to `contact` table |
| 7 | DM-draft agent: prompt engineering, tone variants, threshold logic, persisted to `dm_draft` table |
| 8 | Dashboard: KPI tiles (total raised, avg engagement, companies tracked), main table, per-row expander with contacts + DM |
| 9 | README with architecture diagram, scope decisions, "what I'd do with another week" section |
| 10 | Loom walkthrough (3–5 min): problem framing → live demo → tradeoff discussion → code tour of the agent layer |

**Checkpoints:**

- **End of hour 4:** agent runs end-to-end, writes real PH data + mock data to SQLite. If not there by hour 5, cut HN and enrichment scope by half.
- **End of hour 7:** all three agent passes (ingest, enrich, draft) working on at least one row. If not there, ship without the DM bonus and flag it in README as "implemented but not merged due to timebox."

## 9. What This Plan Demonstrates

- **Scope judgment.** Explicit decisions about what to build, mock, and omit — with reasoning a senior reviewer can evaluate.
- **AI engineering fundamentals.** Multi-step agent with `tool_use`, structured outputs via Pydantic, prompts as versioned artifacts, chained LLM operations.
- **Awareness of production gaps.** Non-goals section shows I know what a real version needs; I just didn't pretend to build it in 2 days.
- **Communication.** README + Loom convert tradeoffs into evidence, not excuses.

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Product Hunt GraphQL auth changes or rate-limits mid-build | Fall back to a cached response snapshot; the agent logic doesn't care about the source |
| Agent returns malformed structured output | Pydantic validation + one retry with the validation error injected into the next turn |
| Timebox overrun on enrichment or DM bonus | Both are behind feature flags; ship core ingestion first, layer bonuses on top |
| Reviewer expects live data during walkthrough | Loom recorded with real data pulled fresh; live demo as backup, not primary artifact |
