# Lean In Circle Recommendations

An API that returns a ranked list of Circles for a member, each with a short, member-facing reason it was recommended.

- **Design doc (1 page):** [`DESIGN.md`](DESIGN.md)
- **Database schema + indexing rationale:** [`docs/schema.md`](docs/schema.md) · DDL in [`app/schema.sql`](app/schema.sql)
- **Example responses for the planted scenarios:** [`examples/`](examples)

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m app.seed                 # builds circles.db from data/*.json (the API also does this on first start)
uvicorn app.api:app --reload       # http://localhost:8000/docs for interactive Swagger UI
```

```bash
curl "localhost:8000/users/7/recommendations"
curl "localhost:8000/users/15/recommendations?limit=10&debug=true"
```

There's also a terminal view, which is handy for walking through scenarios:

```bash
python -m app.cli 23 --debug
```

Run the tests (108 tests: the 4 planted scenarios, invariants checked for all 100 users, and the HTTP layer):

```bash
pytest -q
```

## API

### `GET /users/{user_id}/recommendations`

| Query param | Default | Notes |
| --- | --- | --- |
| `limit` | 5 | 1–20 |
| `debug` | false | Adds the score breakdown per result, the member's inferred interests, and every excluded Circle with the reason |

```jsonc
{
  "user_id": 15,
  "strategy": "personalized",            // or "cold_start"
  "as_of": "2026-09-20T18:00:00+00:00",  // the "now" used for recency
  "recommendations": [
    {
      "rank": 1,
      "circle": { "id": 11, "name": "The Negotiation Table", "topic": "negotiation", "format": "hybrid",
                  "join_policy": "open", "member_count": 15, "max_members": 25, "spots_left": 10, ... },
      "explanation": "Focused on Negotiation, a topic you follow. Very active: 13 posts this month, last active yesterday. Meets in person and online · open to join.",
      "reasons": [
        { "code": "topic_match", "text": "Focused on Negotiation, a topic you follow." },
        { "code": "active",      "text": "Very active: 13 posts this month, last active yesterday." },
        { "code": "joinable",    "text": "Meets in person and online · open to join." },
        { "code": "leader",      "text": "Led by Sofia, Marketing Lead." }
      ],
      "match_type": "personalized",       // or "discover" (backfill / cold start)
      "similar_circles": [ { "id": 10, "name": "Negotiation Circle" }, { "id": 12, "name": "Negotiate Like a Leader" } ]
    }
  ],
  "prompt": "Pick a few topics you care about..."   // only when she has no stated interests
}
```

`404` for an unknown user, `422` for an invalid `limit`. `GET /health` is a liveness check.

## Planted scenarios: what comes back

| Scenario | User | Result (top 5) | Why |
| --- | --- | --- | --- |
| Cold start | 42 | #11 Negotiation Table, #5 Women Who Lead, #39 Mentorship Matters, #24 Burnout to Balance, #31 Team Leads | No signals → the healthiest **open** Circles, one per topic, labelled `discover`, plus a `prompt` to pick interests. |
| Obvious matches | 7 | **#5 Women Who Lead, #6 Speak Up Circle**, then #31, #34, #14 | Primary-topic matches on both of her interests. #6 also covers her second topic; #5 has 4 members in her city (Seattle). |
| Duplicates | 15 | #11 Negotiation Table (with #10 and #12 as `similar_circles`), #13 Confident Voices, … | Collapsed to the best Circle per topic; the near-copies stay one tap away instead of filling the list. |
| Full / inactive | 23 | **#22 Level Up Collective** first; #20 and #21 never appear | `debug=true` shows `#20: full`, `#21: inactive`. The life-stage gate also keeps out "Working Mothers United", which shares a tag but isn't something she said applies to her. |

## Project layout

```
app/
  api.py              FastAPI app + response models
  service.py          wires DB → ranker → response
  repository.py       all SQL; returns dataclasses
  features.py         derived Circle health (full / inactive / health_score)
  seed.py             JSON → SQLite, then computes features
  schema.sql          DDL
  config.py           every weight and threshold in one place
  cli.py              terminal view
  recommender/
    signals.py        profile → weighted interests (stated / bio / existing Circles)
    ranking.py        eligibility → score → collapse duplicates → backfill
    explain.py        grounded, template-based explanations
tests/test_recommendations.py
data/                 seed dataset (unchanged); generate.mjs regenerates it
examples/             debug output for users 7, 15, 23, 42
```

## Configuration

| Env var | Default | |
| --- | --- | --- |
| `RECS_DB_PATH` | `./circles.db` | |
| `RECS_DATA_DIR` | `./data` | |
| `RECS_AS_OF` | snapshot time (latest `last_activity_at`) | ISO timestamp used as "now" for recency. Re-run `python -m app.seed` after changing it so the health features are recomputed. |

Ranking weights and thresholds live in [`app/config.py`](app/config.py), each with a comment explaining it.

## How I used AI

I built this with Claude as a pair programmer. I set the direction and made the product calls. Claude explored the dataset, drafted the modules and tests, and ran the scenarios so we could iterate on the output. Where the first output was wrong, I changed the approach rather than tweaking numbers to pass a test:

- **#5 Women Who Lead first lost to #1 Elevation Circle for user 7** (both are leadership Circles). Rather than raise a weight until #5 won, I asked what a member would actually care about. Circles have no location field, so I used the cities of current members as a proxy for "can she attend in person?", which surfaces #5 (4 members in Seattle) for a reason the member can see.
- **User 23 was shown "Working Mothers United"** because of a shared `getting-promoted` tag. Technically relevant, but presumptuous for the member, so I added the life-stage gate.
- **Explanation wording** was tightened to claims the data supports ("Also covers X" instead of "members regularly discuss X"; "one of the most active" instead of "welcoming").

Each of these is now a test, so the decisions can't quietly regress.
