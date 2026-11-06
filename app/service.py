"""Glue between the DB, the ranker and the API response shape."""
from __future__ import annotations

import sqlite3

from . import repository as repo
from .features import resolve_as_of
from .recommender.explain import explain
from .recommender.ranking import rank


class UserNotFound(Exception):
    pass


def recommend(conn: sqlite3.Connection, user_id: int, limit: int, debug: bool = False) -> dict:
    user = repo.get_user(conn, user_id)
    if user is None:
        raise UserNotFound(user_id)
    labels = repo.topic_labels(conn)
    candidates = repo.get_discoverable_circles(conn, exclude_ids=user.member_circle_ids, user_location=user.location)
    result = rank(user, candidates, limit)
    cold = result.strategy == "cold_start"

    recs = []
    for i, s in enumerate(result.items, start=1):
        c = s.circle
        text, reasons = explain(s, labels, cold, user.location)
        item = {
            "rank": i,
            "circle": {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "topic": c.topic,
                "topic_label": labels.get(c.topic or ""),
                "format": c.format,
                "join_policy": c.join_policy,
                "member_count": c.member_count,
                "max_members": c.max_members,
                "spots_left": c.spots_left,
                "cover_image_url": c.cover_image_url,
            },
            "explanation": text,
            "reasons": reasons,
            "match_type": s.bucket,
            "similar_circles": [{"id": x.id, "name": x.name} for x in s.similar],
        }
        if debug:
            item["debug"] = {
                "score": s.score,
                "relevance": round(s.relevance, 4),
                "health_score": c.health_score,
                "matches": [m.__dict__ for m in s.matches],
                "adjustments": s.adjustments,
            }
        recs.append(item)

    out: dict = {
        "user_id": user.id,
        "strategy": result.strategy,
        "as_of": resolve_as_of(conn).isoformat(),
        "recommendations": recs,
    }
    if cold or not user.stated_topics:
        out["prompt"] = "Pick a few topics you care about to get Circles matched to your goals."
    if debug:
        out["debug"] = {
            "interests": {t: {"weight": i.weight, "source": i.source} for t, i in result.interests.items()},
            "excluded": [{"id": c.id, "name": c.name, "reason": r} for c, r in result.excluded],
        }
    return out
