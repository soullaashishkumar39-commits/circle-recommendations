"""Circle health features: is it full, is it alive, and how healthy is it (0..1)?

Run at seed time here; in production this is a scheduled batch job writing
`circle_features`, so the request path only reads precomputed numbers.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def resolve_as_of(conn: sqlite3.Connection) -> datetime:
    if config.AS_OF_OVERRIDE:
        return parse_ts(config.AS_OF_OVERRIDE)
    row = conn.execute("SELECT value FROM dataset_meta WHERE key = 'snapshot_as_of'").fetchone()
    if row:
        return parse_ts(row["value"])
    return datetime.now(timezone.utc)


def _p90(values: list[float]) -> float:
    if not values:
        return 1.0
    s = sorted(values)
    return max(s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))], 1e-9)


def _log_norm(x: float, ref: float) -> float:
    """log-scaled, capped at 1.0 at the reference (p90) value."""
    return min(1.0, math.log1p(max(x, 0)) / math.log1p(ref))


def compute_circle_features(conn: sqlite3.Connection, as_of: datetime) -> None:
    window_start = (as_of - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    engagement = {
        r["circle_id"]: (r["n"], r["eng"])
        for r in conn.execute(
            """
            SELECT circle_id,
                   COUNT(*) AS n,
                   SUM(reaction_count + 2 * comment_count + 2 * save_count) AS eng
            FROM posts
            WHERE created_at >= ?
            GROUP BY circle_id
            """,
            (window_start,),
        )
    }

    raw = []
    for c in conn.execute("SELECT * FROM circles"):
        last = parse_ts(c["last_activity_at"]) if c["last_activity_at"] else None
        days_since = (as_of - last).total_seconds() / 86400 if last else 9999.0
        n_posts, eng_sum = engagement.get(c["id"], (0, 0))
        eng_per_post = (eng_sum / n_posts) if n_posts else 0.0
        is_full = c["max_members"] is not None and c["member_count"] >= c["max_members"]
        is_inactive = (
            days_since > config.INACTIVE_AFTER_DAYS
            or c["feed_posts_30d"] < config.MIN_POSTS_30D_FOR_ACTIVE
        )
        raw.append(
            dict(
                circle_id=c["id"],
                days_since=max(days_since, 0.0),
                posts=c["feed_posts_30d"],
                chat=c["chat_messages_30d"],
                eng=eng_per_post,
                is_full=is_full,
                is_inactive=is_inactive,
            )
        )

    # Normalise against live Circles only, so dead ones don't drag the scale down.
    live = [r for r in raw if not r["is_inactive"]] or raw
    ref_posts = _p90([r["posts"] for r in live])
    ref_chat = _p90([r["chat"] for r in live])
    ref_eng = _p90([r["eng"] for r in live])
    w = config.HEALTH_WEIGHTS

    conn.execute("DELETE FROM circle_features")
    for r in raw:
        recency = 0.5 ** (r["days_since"] / config.RECENCY_HALF_LIFE_DAYS)
        health = (
            w["posts"] * _log_norm(r["posts"], ref_posts)
            + w["chat"] * _log_norm(r["chat"], ref_chat)
            + w["engagement"] * _log_norm(r["eng"], ref_eng)
            + w["recency"] * recency
        )
        conn.execute(
            """
            INSERT INTO circle_features
              (circle_id, computed_as_of, days_since_activity, posts_30d,
               engagement_per_post, is_full, is_inactive, health_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["circle_id"],
                as_of.isoformat(),
                round(r["days_since"], 2),
                r["posts"],
                round(r["eng"], 2),
                int(r["is_full"]),
                int(r["is_inactive"]),
                round(health, 4),
            ),
        )
    conn.commit()
