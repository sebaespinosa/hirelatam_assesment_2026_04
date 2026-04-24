# What Counts as a "Launch"

Working definition for the launch classifier (Phase 2 of `PHASES.md`).

Grounded in ~31 reference X posts provided as positive examples. Because X blocks direct fetching, the full text of each reference post is filled in manually in `evals/launch_classifier.jsonl`. This document captures the *pattern* that emerged from analyzing the handles, companies, and surrounding search context.

## 1. Core Definition

A **launch post** is a first-person announcement from a founder, maker, or official company account introducing something new, specific, and usable (or imminently usable) to the world.

Three properties are required. If any is missing, it's not a launch.

1. **Novelty.** Something that didn't exist (or wasn't publicly available) before this post. New product, new feature that materially changes the product's capability, new company, new round of funding, new major milestone that signals a shift in company state.
2. **Specificity.** A named, identifiable thing — not a vibe, not a teaser, not a thread about the industry. The post or the linked media makes clear *what* is being announced.
3. **Agency.** Posted by the person or entity doing the launching, not by a commentator. Retweets, reaction threads, "I love X, you should try it" posts are not launches even when they concern a launch.

## 2. Launch Types

The reference set covers four recurring types. The classifier should tag each post with one:

| Type | Description | Example signals |
|---|---|---|
| `product` | A new product or company going public / available | "Introducing", "Today we're launching", "Meet [X]", link to new site, app store, or landing page |
| `feature` | A significant new feature in an existing product that changes what the product does | "Now in [X]", "You can now", feature-specific demo video, changelog-style hero |
| `milestone` | A company-state change: fundraise, ARR milestone, major hire, acquisition, IPO | "$XM raised", "Series A", "we've crossed $YM ARR", valuation number |
| `program` | A batch, cohort, or initiative announcement from an incubator / investor | "Announcing [batch name]", "introducing the [N] companies of [cohort]" (typical of @ycombinator) |

A single post can be classified as only one type; pick the *primary* framing. A Series A post that also teases a new product is still `milestone` unless the product reveal is the headline.

## 3. Positive Signals

From the reference posts, these are the strongest indicators of a launch:

- **Launch vocabulary** — "Introducing", "Announcing", "Today we're launching", "We're excited to share", "Now live", "Ship", "Meet [Product]", "Out now"
- **Ownership language** — "We built", "I built", "Our team shipped", "We've been working on this for [time period]"
- **Concrete call-to-action** — link to a product page, demo URL, app store, waitlist, signup form, Product Hunt page
- **Media attached** — demo video, screenshot of the product, founder-to-camera video, hero graphic
- **Temporal framing** — "Today", "Right now", "As of this morning" — as opposed to retrospective or aspirational framing
- **Numeric milestones in context** — "$200M Series A", "$100M ARR", "10,000 users" when paired with announcement framing
- **Thread structure** — first tweet is the headline; subsequent tweets elaborate. The classifier only sees the first post.

## 4. Negative Signals (looks like a launch, isn't)

These are the edge cases the classifier has to reject correctly. Each has a matching negative in the eval set.

- **Retrospective / commentary** — "A year ago today we launched X" is not a launch; it's a retrospective.
- **Teasers without specifics** — "Something big is coming 👀" has novelty framing but no specificity.
- **Recommendations** — "Everyone should try [Product]" from a non-affiliated account is enthusiasm, not launch.
- **Generic marketing** — "Our tool helps you do X faster" is ongoing marketing, not a launch.
- **Product updates styled as launches** — "We fixed a bug in the CSV export" is a changelog entry, not a launch, even if phrased "Shipped: better CSV export."
- **Industry takes** — Thought-leadership threads about where AI is going are not launches even from founders.
- **Hiring posts** — "We're hiring a chief of staff" is company news but not a launch under this definition. (Debatable; erring on the side of excluding, since hiring posts typically don't map to dashboard metrics.)
- **Waitlist posts without a product** — "Sign up for the waitlist" with no product shown is a teaser. If the post *also* reveals the product, it qualifies.
- **Relaunches / repositionings without new capability** — Rebrand announcements without a product change are borderline; classify as `program` only if they introduce something materially new.

## 5. Edge Cases & Judgment Calls

Ambiguous scenarios to call explicitly in the classifier prompt:

- **Soft launches / beta.** Invite-only or waitlist-gated product reveals count as `product` if the product is shown. The point is newness, not general availability.
- **Fundraise + product in one post.** Classify by headline framing. If the tweet leads with the raise number, `milestone`. If it leads with the product and mentions the raise in passing, `product`.
- **YC-style batch announcements.** @ycombinator posting "introducing the W25 batch" is a `program` launch. A single YC company's own launch tweet is `product`.
- **Milestone posts from the same company within days.** Each independent milestone (ARR, hire, office open) is its own launch event. Deduplicate downstream in the pipeline, not at classification time.
- **Revivals / re-launches.** If a dormant product is actively relaunched with new positioning, `product`. If it's just a pricing change, not a launch.

## 6. Output Schema

The classifier returns:

```json
{
  "is_launch": true,
  "confidence": 0.0,
  "launch_type": "product" | "feature" | "milestone" | "program" | null,
  "reasoning": "one or two sentences citing which signals fired"
}
```

- `confidence` below 0.6 → route to manual review queue (dashboard tab).
- `launch_type` is `null` iff `is_launch` is false.

## 7. Metrics the Classifier Must Hit

On the eval set in `evals/launch_classifier.jsonl`:

- **Precision on positives ≥ 0.90** — false positives pollute the dashboard and waste DM-draft budget downstream
- **Recall on positives ≥ 0.85** — some miss is acceptable; the dashboard can show low-confidence items separately
- **Negative accuracy ≥ 0.90** — rejecting commentary, teasers, and updates is the main value-add of having a classifier at all

If either metric falls below target, iterate on the few-shot examples in `prompts/launch_classifier.md` before adding more prompt instructions. Examples are higher-leverage than prose.
