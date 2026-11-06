# Technical design: Circle recommendations

**Goal.** Suggest Circles a member is likely to join *and stay in*. A Circle that's full, dormant or a near-copy of one already listed costs her trust and adds nothing. So every rule below asks the same question: will she find people here who show up?

## What I built
A FastAPI service backed by SQLite: `GET /users/{id}/recommendations?limit=5&debug=false`. The pipeline is a set of pure functions over dataclasses (the SQL lives only in `repository.py`), so each stage can be tested on its own:

1. **Eligibility (hard gates).** Drop a Circle if she's already in it, it's **full** (`member_count >= max_members`), it's **dormant** (no activity in 45 days or 0 posts in 30), it's unlisted, or it has no topic. Also drop **life-stage Circles** (motherhood, career breaks, "the only one") unless *she* named that topic or wrote about it in her bio. A tag overlap is not enough reason to assume someone is a mother.
2. **Score = 0.65 × relevance + 0.35 × health + small named adjustments.**
   - *Relevance*: her interests against the Circle's primary topic (1.0) or tags (0.5), weighted by how much I trust the source: stated topics 1.0, bio keywords 0.6, tags of her current Circles 0.3. Extra matched interests add a small bonus (e.g. Speak Up Circle covers both of user 7's topics).
   - *Health* (0–1, computed offline into `circle_features`): posts in 30 days (0.35), chat volume (0.20), engagement per post, where comments and saves count double because a reply is what a new member needs (0.25), and recency with a 10-day half-life (0.20). Each part is log-scaled against the 90th percentile so one very busy Circle doesn't flatten the rest.
   - *Adjustments*: −0.03 for request-to-join, −0.03 for a missing description or cover image, −0.15 if she's already in a Circle on that topic, and location fit (below).
3. **Collapse duplicates.** Show only the best Circle per primary topic; the runners-up go in `similar_circles`. User 15 sees one Negotiation Circle with the other two one tap away, so they're grouped rather than hidden.
4. **Backfill and cold start.** If there are fewer relevant Circles than requested, fill with the healthiest open Circles on topics not already shown, labelled `match_type: "discover"`. A member with no signals at all (user 42) gets a varied set of active, open Circles plus a `prompt` asking her to pick topics, because the best cold-start fix is a better profile.
5. **Explain.** Each result gets three grounded parts: *why you* ("Focused on Negotiation, a topic you follow."), *proof of life* ("13 posts this month, last active yesterday.") and *how to join* ("Meets in person and online · 4 members based in Seattle, WA · open to join."). `reasons[]` holds the same parts as codes so the UI can render chips.

**Signals I used and left out.** Used: stated topics, bio, existing memberships, location, every activity field, capacity, join policy, format. Not used: **job title, company, industry** ("Product Manager" doesn't mean she manages people, and an explanation based on her employer would feel invasive), **profile completeness / photo** (these describe *her*, not her fit, and they would penalise exactly the new members who need a Circle most), and **identity inference** from names or fields. Circles have no location, so in-person fit uses how many current members share her city: +0.02 per nearby member (up to 4), or −0.05 for an in-person-only Circle where nobody nearby shows up (−0.10 if she says "Remote").

## Tradeoffs
- **Templates over an LLM for explanations.** Every sentence traces back to a field, nothing about a Circle can be made up, output is deterministic and testable, and it costs nothing per request. Rewriting the text with an LLM for warmth is a good later step, once a check that it states nothing beyond the reasons is in place.
- **A hand-tuned linear score over a learned model.** There's no join or retention data to train on, and the weights sit in `config.py` for review. I sanity-checked them against the planted scenarios and all 100 users. The risk is overfitting to 40 Circles; the fix is the logging described below.
- **One Circle per topic** is blunt: two different leadership Circles collapse together. I accepted that for a clean, explainable result; topic plus text similarity would be finer.
- **"Now" = snapshot time** (`2026-09-20`), because otherwise every Circle in the frozen data would look dormant. Override it with `RECS_AS_OF`.

## At production scale
- **Precompute health** with a scheduled job (or streaming counters) into `circle_features`; the request path already only reads it.
- **Candidate generation by index**: `WHERE access='public' AND topic_slug IN (:interests)` on `(access, topic_slug)` plus a cached popular pool per region, so the ranker scores hundreds of Circles, not 170k. Cache responses per user for a few minutes and invalidate on join or interest change.
- **Postgres** with the same schema, plus a `location`/`timezone` column on Circles in place of the member-city proxy.
- **Log impressions → joins → still active at 30 days**, then A/B the weights and move to a learned ranker (e.g. gradient-boosted trees on these same features) once there's labelled data. Track how recommendations spread across Circles so small new Circles aren't starved by popular ones.

## With more time
Collaborative signal ("members of Circles like yours also joined…"), embedding-based duplicate detection on name and description, a boost for small new Circles that still need members, timezone matching for virtual Circles, and an evaluation script with ranking metrics over held-out memberships.
