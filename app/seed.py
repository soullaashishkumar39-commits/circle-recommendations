"""Build circles.db from the seed JSON.  Usage:  python -m app.seed"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import config
from .db import connect
from .features import compute_circle_features, resolve_as_of

SCHEMA = Path(__file__).with_name("schema.sql")


def _load(name: str):
    return json.loads((config.DATA_DIR / name).read_text(encoding="utf-8"))


def seed(db_path: Path | str | None = None) -> Path:
    db_path = Path(db_path or config.DB_PATH)
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    conn.executescript(SCHEMA.read_text())

    topics, users = _load("topics.json"), _load("users.json")
    circles, memberships, activity = _load("circles.json"), _load("memberships.json"), _load("activity.json")

    conn.executemany(
        "INSERT INTO topics (id, slug, label, domain) VALUES (?, ?, ?, ?)",
        [(t["id"], t["slug"], t["label"], t["domain"]) for t in topics],
    )
    conn.executemany(
        """INSERT INTO users (id, first_name, last_name, has_photo, bio, job_title, company,
                              industry, location, joined_at, profile_completeness)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (u["id"], u["first_name"], u["last_name"], int(u["has_photo"]), u["bio"], u["job_title"],
             u["company"], u["industry"], u["location"], u["joined_at"], u["profile_completeness"])
            for u in users
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO user_topic_interests (user_id, topic_slug) VALUES (?, ?)",
        [(u["id"], slug) for u in users for slug in u["topic_interests"]],
    )
    conn.executemany(
        """INSERT INTO circles (id, name, slug, description, topic_slug, cover_image_url, format, access,
                                join_policy, max_members, member_count, created_at, last_activity_at,
                                feed_posts_30d, chat_messages_30d)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (c["id"], c["name"], c["slug"], c["description"], c["topic"], c["cover_image_url"], c["format"],
             c["access"], c["join_policy"], c["max_members"], c["member_count"], c["created_at"],
             c["last_activity_at"], c["feed_posts_30d"], c["chat_messages_30d"])
            for c in circles
        ],
    )
    # Tags arrive with occasional duplicates (e.g. circle 17) — the PK + OR IGNORE dedupes them.
    conn.executemany(
        "INSERT OR IGNORE INTO circle_tags (circle_id, tag) VALUES (?, ?)",
        [(c["id"], tag) for c in circles for tag in c["tags"]],
    )
    conn.executemany(
        "INSERT INTO memberships (user_id, circle_id, role, joined_at) VALUES (?, ?, ?, ?)",
        [(m["user_id"], m["circle_id"], m["role"], m["joined_at"]) for m in memberships],
    )
    conn.executemany(
        """INSERT INTO posts (id, circle_id, author_user_id, body, reaction_count, comment_count,
                              save_count, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (a["id"], a["circle_id"], a["author_user_id"], a["body"], a["reaction_count"],
             a["comment_count"], a["save_count"], a["created_at"])
            for a in activity
        ],
    )
    snapshot = max(c["last_activity_at"] for c in circles if c["last_activity_at"])
    conn.execute("INSERT INTO dataset_meta (key, value) VALUES ('snapshot_as_of', ?)", (snapshot,))
    conn.commit()

    compute_circle_features(conn, resolve_as_of(conn))
    conn.close()
    return db_path


if __name__ == "__main__":
    path = seed(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Seeded {path}")
