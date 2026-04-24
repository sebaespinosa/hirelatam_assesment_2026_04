# How to Populate the Eval Set

`evals/launch_classifier.jsonl` ships with 31 positive placeholders and 12 completed negative examples. The positives need post text before the classifier can be meaningfully evaluated.

## Why you're pasting manually

X blocks automated fetching (robots.txt), paid API access is now pay-per-use with no free tier, and community scrapers violate ToS. For a 2-day assessment, the 10–15 minutes of manual pasting is cheaper than any automation path.

## How to fill each entry

For each `pos_NNN` line, open the URL in a browser and paste:

- **`post_text`** — the full tweet text. Strip t.co links if you want; keep emojis and hashtags. If it's a thread, use only the first tweet (what the classifier sees at ingestion time).
- **`media`** — one of `"video"`, `"screenshot"`, `"image"`, `"link"`, `null`. Used as a signal by the classifier; don't skip.
- **`likes`** and **`reposts`** — integers. Needed for the engagement-score column downstream; also lets the DM-draft pass identify "underperforming" launches.
- **`expected.launch_type`** — replace `null` with `"product"`, `"feature"`, `"milestone"`, or `"program"` based on the definition in `docs/launch_definition.md`.

## Quality bar

- Don't paraphrase. The classifier sees the exact text; noise in the eval set means noise in the metrics.
- If a post turns out to **not** be a launch by the working definition (e.g., you discover `pos_014` is actually commentary), **move it to negatives** — flip `expected.is_launch` to `false` and add a one-sentence reasoning field. This is a feature, not a problem; it means your reference set and your definition are both improving.
- For `pos_016` (the malformed Merit Systems URL), either find the correct status ID or delete the entry.

## Running the eval

Once populated:

```bash
python -m evals.run_classifier evals/launch_classifier.jsonl
```

Outputs precision, recall, and negative accuracy per the targets in §7 of the launch definition (≥ 0.90 / ≥ 0.85 / ≥ 0.90). If you miss a target, iterate on few-shot examples in `prompts/launch_classifier.md` — not on the prose rules.

## Keeping the eval fresh

Every time you see the classifier miss a case in production (dashboard run log), copy that case into the eval set as a new entry with the correct expected label. This turns the eval set into a regression suite, which is the payoff of having one at all.
