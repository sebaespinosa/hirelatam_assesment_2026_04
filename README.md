# Assesment Requirements

Build a custom dashboard using AI tools like Claude Code or Codex to pull launch videos from platforms like X, LinkedIn, as well as fundraise announcements from Google, crunchbase, and other company fundraise databases or incubators (ie YCombinator). Map out in the dashboard how much each company has raised, how many likes their launch got on X and LinkedIn. Bonus - For each new data point in the dashboard, add in an enriched contact methods box that includes email, phone number, linkedin, and X. Double Bonus - Add in functionality that drafts DMs to launches that did poorly.

## What was built

The assesment has been approach with a POC (Proof of Concept), since establishing real integrations with the providers is a more complex/time consuming process. The goal is to prove how I work with AI Tools, how to approach solutions, and proof of feasibility of building what's requested on the assignment.

For this purpose, only a real integration with "Product Hunt" was impolemented, since it has a public/free API to integrate. Data for other providers was mock. Also, I decide to use Streamlite to have everything built in a single component, no separation on FrontEnd + BackEnd + Agent to avoid complexity. Many UI/UX considerations where exclude as well.

## Demo

Live site: 

To build locally

### Prerequisites

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) (dependency manager)
- `OPENAI_API_KEY` — any tier works, classifier + orchestrator are on `gpt-4o-mini` / `gpt-4o`
- `PH_DEVELOPER_TOKEN` — register a non-OAuth "Developer Token" at [Product Hunt developer settings](https://api.producthunt.com/v2/oauth/applications); the OAuth callback URL is a required form field but never invoked (use `https://example.com` or similar)

```bash
make install       # uv sync
cp .env.example .env   # then fill in the two keys
make demo          # init-db + ingest + enrich + DM draft (~5 min, ~15¢ of OpenAI spend)
make dashboard     # streamlit on http://localhost:8501
```

Mermaid sequence diagram



### What's real, what's mocked

| Source                       | Status        | Notes |
|------------------------------|---------------|-------|
| **Product Hunt**             | ✅ Real       | Free GraphQL, Bearer token via `PH_DEVELOPER_TOKEN`. Live fetch falls back to `data/seed/ph_snapshot.json` on any network failure. |
| X / Twitter                  | 🟠 Mocked     | Paid-only as of Feb 2026; Twikit-style scrapers are ToS-noncompliant. Community MCPs all wrap the paid API. |
| LinkedIn                     | 🟠 Mocked     | No public engagement API; *hiQ v. LinkedIn* ongoing. A real integration is 1–2 days on its own. |
| Crunchbase                   | 🟠 Mocked     | Free tier too gated for prototype volume. |
| Y Combinator                 | 🟠 Mocked     | Directory is scrape-able in principle; cut for time in favour of a clean mock. |

Mocked data is generated **once** by a Claude-side prompt ([`prompts/mock_generator.md`](prompts/mock_generator.md)) and saved to committed JSON seeds under `data/seed/mock_*.json`. Every mocked row is tagged `source="mock_*"` and rendered with a `:orange-badge[MOCK]` badge in the dashboard. A reviewer who spots undisclosed mock data loses trust in the whole deliverable — explicit labelling is scope discipline, not apology.

### The AI-engineering parts

Four artifacts that I'd point a reviewer at first:

1. **Launch classifier** — [`prompts/launch_classifier.md`](prompts/launch_classifier.md) (v1 versioned). Structured Outputs via OpenAI `response_format={"type": "json_schema", "strict": true}`; Pydantic cross-field invariant (`launch_type` non-null iff `is_launch=true`); eval set at [`evals/launch_classifier.jsonl`](evals/launch_classifier.jsonl) with a runner at [`evals/run_classifier.py`](evals/run_classifier.py) that exits non-zero if precision/recall/negative-accuracy targets regress.
2. **Ingestion orchestrator** — [`prompts/orchestrator.md`](prompts/orchestrator.md) + [`src/agent/tools.py`](src/agent/tools.py) + [`src/agent/orchestrator.py`](src/agent/orchestrator.py). Generic OpenAI function-calling loop with per-source sequencing, parallel tool calls within a source, Pydantic validation errors surfaced to the agent as `{"error": ..., "code": "validation_error"}` for self-correction.
3. **Enrichment orchestrator** — [`prompts/enrichment.md`](prompts/enrichment.md) + [`src/agent/enrichment_tools.py`](src/agent/enrichment_tools.py). Same generic loop, different tool bundle. Mocked `find_*` backends are deterministic (seeded by `hashlib.md5(company_name + field)`) so re-runs are idempotent.
4. **DM-draft orchestrator** — [`prompts/dm_draft.md`](prompts/dm_draft.md) + [`src/agent/dm_tools.py`](src/agent/dm_tools.py) + [`src/agent/thresholds.py`](src/agent/thresholds.py). Per-source P25 threshold computes "under-performing" relative to peers; agent drafts warm, specific, ≤80-word DMs with an explicit anti-pattern list ("never name the underperformance").

Every prompt is markdown — committed, versioned, git-diffable. The runtime reads the prompt file and strips the metadata header; the `**Version:**` line is the source of truth for prompt version, which the DM-draft handler auto-injects into `dm_draft.prompt_version`.

The second Streamlit tab, **Agent Run Log**, is the demo centrepiece. It loads the latest JSONL run and renders turn-by-turn assistant messages, per-tool args + results expanders, a tool-call histogram, and the final summary. That tab is what makes the AI engineering visible to a reviewer who doesn't read code.






### Layout

```
run_agent.py            # ingestion agent CLI
run_enrichment.py       # enrichment agent CLI
run_dm_drafts.py        # DM-draft agent CLI
dashboard.py            # Streamlit UI (two tabs)
src/
  agent/                # generic loop + 3 tool bundles + thresholds
  classifier/           # OpenAI Structured-Outputs launch classifier
  sources/              # producthunt (real) + mocks (loaders + one-shot generator)
  models/               # Pydantic schemas
  db/                   # schema.sql, repo, init script
  dashboard/            # pure-Python query + run-log layer
prompts/                # versioned markdown system prompts
evals/                  # jsonl eval sets + runner
tests/                  # pytest suite
data/
  seed/                 # committed mock JSON + gitignored PH snapshot
  runs/                 # gitignored — one JSONL per agent run
  db.sqlite             # gitignored
docs/                   # launch_definition.md, loom_script.md
PLAN.md                 # original plan: scope decisions + architecture + risks
PHASES.md               # phased implementation order + checkpoints
CLAUDE.md               # instructions for future AI pair-programming sessions
```

## Further reading

- [PLAN.md](PLAN.md) — the 2-day plan as it was written at the start, unedited save for provider swap.
- [PHASES.md](PHASES.md) — phased implementation with checkpoints and cut-points.
- [CLAUDE.md](CLAUDE.md) — invariants + gotchas captured during implementation.
- [docs/launch_definition.md](docs/launch_definition.md) — the classifier's ground truth.
- [docs/manual_test.md](docs/manual_test.md) — ~15-minute QA pass to run before recording the Loom.
