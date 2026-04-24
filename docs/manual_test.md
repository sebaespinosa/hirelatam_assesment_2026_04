# Manual Test Walkthrough

A ~15-minute pass to verify the app end-to-end before recording the Loom or handing to a reviewer. Run sections A–D in order on a fresh clone (or after `rm -f data/db.sqlite data/runs/*.jsonl`). Section E is negative testing; F is a troubleshooting reference.

## A. Pre-flight (30s)

```bash
cat .env                # OPENAI_API_KEY and PH_DEVELOPER_TOKEN both set
uv run pytest -q        # expect: 142 passed
uv run ruff check .     # expect: "All checks passed!"
```

If tests fail or ruff trips, **stop**. Nothing downstream is worth checking until the green-bar baseline is restored.

## B. Fresh pipeline run (~5 min)

Wipe state and run the pipeline the way a reviewer would:

```bash
rm -f data/db.sqlite data/runs/*.jsonl
make demo
```

### Expected output per pass

| Pass            | Time     | Summary (approximate)                                                 |
|-----------------|----------|-----------------------------------------------------------------------|
| `run_agent`     | ~4 min   | `turns=~11`, `tool_calls=~141`, `finished=True`. PH ~18/20 rejected. `mock_x` 20, `mock_linkedin` 15, `mock_crunchbase` 30, `mock_yc` 15 all persisted. |
| `run_enrichment`| 1–2 min  | `finished=True`, `contacts_persisted` ≈ 78.                           |
| `run_dm_drafts` | ~15 s    | `finished=True`, `drafts_persisted: 5`.                               |

### Red flags

- `finished=False` on any pass — the agent ran out of turns or broke the loop. Re-run that pass once; enrichment is idempotent, DM drafts would duplicate so prefer `--max-turns 20` instead if bumping.
- `errors > 0` in any summary — open the matching JSONL in `data/runs/` and grep `"code"`. Validation errors that didn't self-correct point to a prompt regression.

### DB sanity after the run

```bash
uv run python -c "
from src.db import get_connection
c = get_connection()
for t in ['company','launch','funding_round','contact','dm_draft']:
    print(f'{t}: {c.execute(f\"SELECT COUNT(*) FROM {t}\").fetchone()[0]}')
"
```

Expect roughly: 78 companies · 35 launches · 30 funding rounds · 78 contacts · 5 DM drafts.

## C. Dashboard click-through (~5 min)

```bash
make dashboard   # http://localhost:8501
```

### Dashboard tab

1. **KPI tiles** render non-zero. Total raised in the tens of millions; avg engagement ~500–1500.
2. **Top-10 chart** — 10 bars, descending, visibly differing heights.
3. **Source filter** (sidebar):
   - Select only `producthunt` → table shrinks to PH-attributed companies.
   - Deselect all → info message "No data matches the selected filters.", no traceback.
4. **MOCK badges** — appear on mocked rows, not on PH rows.
5. **Main table** sorts by clicking column headers. Sort by "Total raised (USD)" descending → matches top-10 chart order.
6. **Company selectbox** — pick a company that has ✓ in Contacts and DM draft columns. Easiest path: deselect `mock_yc` + `mock_crunchbase` in the sidebar first.
7. **Per-company detail panel** — four sub-tabs:
   - **Launches** — title, source, posted date, engagement score, classifier reasoning visible.
   - **Funding** — table of rounds (empty for X/LI/YC-only companies — correct).
   - **Contacts** — email/phone/linkedin/X lines, with some `—` placeholders reflecting the deterministic miss rates.
   - **DM drafts** — subject + body in a text area. Verify: company named, ≤80 words, no "your launch underperformed", tone field set, prompt version `v1`.

### Agent Run Log tab

1. **Run selector** lists recent runs with tags (`ingestion`, `enrichment`, `dm_drafts`). Start with the DM-drafts run — smallest, fastest.
2. **5 KPI tiles at top**: Turns, Tool calls, Duration, Status ✓ finished, Model `gpt-4o`.
3. **Tool histogram**:
   - DM drafts run: `list_underperforming_launches` 1, `persist_dm_draft` 5, `finish` 1.
   - Ingestion run: `classify_launch` ~55, `persist_launch` ~35, `persist_funding` 30, `persist_company` 15.
4. **Events list** — expand 2–3:
   - `tool_call` event shows `args` and `result` JSON.
   - `assistant` event shows `tokens_in`/`tokens_out`.
   - Last event is `finish` with summary dict.

## D. Targeted sanity checks (~3 min)

Prove the UI matches the DB. Run these while the dashboard is open:

```bash
# Cross-check "launches flagged for outreach" KPI
uv run python -c "
from src.db import get_connection
c = get_connection()
print('distinct flagged launches:',
      c.execute('SELECT COUNT(DISTINCT launch_id) FROM dm_draft').fetchone()[0])
"

# Cross-check top-5 raised
uv run python -c "
from src.db import get_connection
c = get_connection()
for row in c.execute('''
    SELECT company.name, SUM(f.amount_usd)
    FROM funding_round f
    JOIN company ON company.id = f.company_id
    GROUP BY company.id
    ORDER BY 2 DESC
    LIMIT 5
'''):
    print(row)
"
```

Both must match the dashboard exactly.

## E. Negative testing (~2 min)

Worth running — these failure modes are part of the demo story.

1. **Dry run** — `uv run python run_agent.py --dry-run --max-turns 4`. Tool calls log to JSONL; DB unchanged (`SELECT COUNT(*) FROM company` matches pre-run value).
2. **Snapshot fallback** — temporarily unset `PH_DEVELOPER_TOKEN`:

   ```bash
   mv .env .env.bak && uv run python -m src.sources.producthunt --days 3 --no-persist; mv .env.bak .env
   ```

   Should print `Live fetch failed…; falling back to snapshot.` and proceed using `data/seed/ph_snapshot.json`. Restore `.env` after.
3. **Classifier eval** — `make eval-classifier`. Expected: Precision=0, Recall=0, Neg accuracy=1.000, `Skipped: 30 (placeholder post_text)`. Accurate reflection of the current eval set — positives need manual paste.
4. **Empty source filter** — in the dashboard, deselect all sources. Info message, no traceback.

## F. Common issues

| Symptom                                         | Cause                                                     | Fix |
|-------------------------------------------------|-----------------------------------------------------------|-----|
| `PH_DEVELOPER_TOKEN not set`                    | Not running from repo root, or `.env` is named something else | `cd` to repo root; ensure file is literally `.env` |
| `run_agent` finishes with `errors > 0`          | Single tool-call validation failed without self-correction | Open `data/runs/*.jsonl`, grep `"code"`; reinforce the retry rule in `prompts/orchestrator.md` if it's persistent |
| Dashboard shows zero rows after `make demo`     | `data/db.sqlite` wiped between demo and dashboard         | `ls -la data/db.sqlite` — should be multi-KB |
| Dashboard data looks stale                      | Streamlit connection cache holds the old DB file handle   | Top-right "⋮" → Clear cache, or restart `make dashboard` |
| `run_enrichment` hits max-turns without finishing | 78 companies at ~5/batch need ~34 turns; default is 40   | Re-run; it's idempotent (the list query only returns uncovered companies) |
| PH live fetch returns 0 posts                   | Token valid but no posts in the lookback window           | `--days 30` to widen, or run `--from-snapshot` against the committed cache |

## G. Green-light criteria for recording the Loom

All of the following must hold:

- [ ] `uv run pytest -q` → 142 passed
- [ ] `make demo` completes cleanly (`finished=True` on all three passes)
- [ ] Dashboard KPI tiles populated, company table non-empty, top-10 chart rendered
- [ ] Per-company detail panel shows DM draft for at least one company
- [ ] Agent Run Log tab loads, tool histogram renders for both ingestion and DM-drafts runs
- [ ] A spot-checked DM draft reads cleanly enough to say aloud on camera
