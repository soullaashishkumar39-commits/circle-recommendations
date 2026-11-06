"""All SQL lives here. The ranker works on plain dataclasses and never touches the DB."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class UserProfile:
    id: int
    first_name: str
    bio: str | None
    location: str | None
    profile_completeness: float
    stated_topics: list[str]
    member_circle_ids: set[int]
    member_circle_topics: set[str]          # primary topics of Circles she is already in
    member_circle_tags: set[str]            # tags of Circles she is already in


@dataclass
class Leader:
    first_name: str
    job_title: str | None


@dataclass
class CircleCandidate:
    id: int
    name: str
    slug: str
    description: str | None
    topic: str | None
    tags: set[str]
    cover_image_url: str | None
    format: str
    access: str
    join_policy: str
    max_members: int | None
    member_count: int
    feed_posts_30d: int
    chat_messages_30d: int
    days_since_activity: float
    engagement_per_post: float
    is_full: bool
    is_inactive: bool
    health_score: float
    leaders: list[Leader] = field(default_factory=list)
    local_members: int = 0                   # members based in the requesting user's city

    @property
    def spots_left(self) -> int | None:
        return None if self.max_members is None else max(self.max_members - self.member_count, 0)


def topic_labels(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["slug"]: r["label"] for r in conn.execute("SELECT slug, label FROM topics")}


def get_user(conn: sqlite3.Connection, user_id: int) -> UserProfile | None:
    u = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if u is None:
        return None
    stated = [
        r["topic_slug"]
        for r in conn.execute(
            "SELECT topic_slug FROM user_topic_interests WHERE user_id = ? ORDER BY topic_slug", (user_id,)
        )
    ]
    mem_rows = conn.execute(
        """SELECT c.id, c.topic_slug FROM memberships m JOIN circles c ON c.id = m.circle_id
           WHERE m.user_id = ?""",
        (user_id,),
    ).fetchall()
    circle_ids = {r["id"] for r in mem_rows}
    tags: set[str] = set()
    if circle_ids:
        q = ",".join("?" * len(circle_ids))
        tags = {r["tag"] for r in conn.execute(f"SELECT tag FROM circle_tags WHERE circle_id IN ({q})", tuple(circle_ids))}
    return UserProfile(
        id=u["id"],
        first_name=u["first_name"],
        bio=u["bio"],
        location=u["location"],
        profile_completeness=u["profile_completeness"],
        stated_topics=stated,
        member_circle_ids=circle_ids,
        member_circle_topics={r["topic_slug"] for r in mem_rows if r["topic_slug"]},
        member_circle_tags=tags,
    )


def is_city(location: str | None) -> bool:
    return bool(location) and location.strip().lower() != "remote"


def get_discoverable_circles(
    conn: sqlite3.Connection, exclude_ids: set[int], user_location: str | None = None
) -> list[CircleCandidate]:
    """Circles the user isn't already in, joined with precomputed health features.

    Full/inactive/unlisted Circles are *returned* (flagged) rather than filtered in SQL so the
    ranker owns every eligibility rule and debug mode can say why each was dropped. At
    production scale this becomes `WHERE access = 'public' AND topic_slug IN (...)` on
    idx_circles_access_topic, plus a small precomputed "popular" pool for backfill.
    """
    rows = conn.execute(
        """SELECT c.*, f.days_since_activity, f.engagement_per_post, f.is_full, f.is_inactive, f.health_score
           FROM circles c JOIN circle_features f ON f.circle_id = c.id"""
    ).fetchall()
    rows = [r for r in rows if r["id"] not in exclude_ids]
    if not rows:
        return []
    ids = tuple(r["id"] for r in rows)
    q = ",".join("?" * len(ids))
    tags: dict[int, set[str]] = {}
    for t in conn.execute(f"SELECT circle_id, tag FROM circle_tags WHERE circle_id IN ({q})", ids):
        tags.setdefault(t["circle_id"], set()).add(t["tag"])
    leaders: dict[int, list[Leader]] = {}
    for l in conn.execute(
        f"""SELECT m.circle_id, u.first_name, u.job_title FROM memberships m JOIN users u ON u.id = m.user_id
            WHERE m.role = 'leader' AND m.circle_id IN ({q}) ORDER BY m.joined_at""",
        ids,
    ):
        leaders.setdefault(l["circle_id"], []).append(Leader(l["first_name"], l["job_title"]))
    local: dict[int, int] = {}
    if is_city(user_location):
        local = {
            r["circle_id"]: r["n"]
            for r in conn.execute(
                f"""SELECT m.circle_id, COUNT(*) AS n FROM memberships m JOIN users u ON u.id = m.user_id
                    WHERE u.location = ? AND m.circle_id IN ({q}) GROUP BY m.circle_id""",
                (user_location, *ids),
            )
        }

    return [
        CircleCandidate(
            id=r["id"], name=r["name"], slug=r["slug"], description=r["description"], topic=r["topic_slug"],
            tags=tags.get(r["id"], set()), cover_image_url=r["cover_image_url"], format=r["format"],
            access=r["access"], join_policy=r["join_policy"], max_members=r["max_members"],
            member_count=r["member_count"], feed_posts_30d=r["feed_posts_30d"],
            chat_messages_30d=r["chat_messages_30d"], days_since_activity=r["days_since_activity"],
            engagement_per_post=r["engagement_per_post"], is_full=bool(r["is_full"]),
            is_inactive=bool(r["is_inactive"]), health_score=r["health_score"], leaders=leaders.get(r["id"], []),
            local_members=local.get(r["id"], 0),
        )
        for r in rows
    ]
