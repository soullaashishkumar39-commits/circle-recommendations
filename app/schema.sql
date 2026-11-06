-- Circle recommendations — SQLite schema
-- Normalised so every signal the ranker uses is a plain, indexable column.
-- Arrays from the seed JSON (user topic_interests, circle tags) become join tables.

PRAGMA foreign_keys = ON;

CREATE TABLE topics (
    id      INTEGER PRIMARY KEY,
    slug    TEXT NOT NULL UNIQUE,
    label   TEXT NOT NULL,
    domain  TEXT NOT NULL
);

CREATE TABLE users (
    id                    INTEGER PRIMARY KEY,
    first_name            TEXT NOT NULL,
    last_name             TEXT NOT NULL,
    has_photo             INTEGER NOT NULL DEFAULT 0,
    bio                   TEXT,
    job_title             TEXT,
    company               TEXT,
    industry              TEXT,
    location              TEXT,
    joined_at             TEXT NOT NULL,          -- ISO-8601 UTC
    profile_completeness  REAL NOT NULL DEFAULT 0
);

-- Stated interests (many-to-many). Separate table so "who cares about topic X"
-- is an index lookup, and so interests can carry metadata later (source, weight, added_at).
CREATE TABLE user_topic_interests (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_slug  TEXT    NOT NULL REFERENCES topics(slug),
    PRIMARY KEY (user_id, topic_slug)
);
CREATE INDEX idx_uti_topic ON user_topic_interests(topic_slug);

CREATE TABLE circles (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    slug               TEXT NOT NULL UNIQUE,
    description        TEXT,
    topic_slug         TEXT REFERENCES topics(slug),   -- nullable: some Circles have no topic
    cover_image_url    TEXT,
    format             TEXT NOT NULL CHECK (format IN ('in_person','virtual','hybrid')),
    access             TEXT NOT NULL CHECK (access IN ('public','unlisted')),
    join_policy        TEXT NOT NULL CHECK (join_policy IN ('open','request')),
    max_members        INTEGER,                         -- NULL = uncapped
    member_count       INTEGER NOT NULL DEFAULT 0,      -- denormalised counter (kept in sync on join/leave)
    created_at         TEXT NOT NULL,
    last_activity_at   TEXT,
    feed_posts_30d     INTEGER NOT NULL DEFAULT 0,      -- rolling aggregates, refreshed by a job
    chat_messages_30d  INTEGER NOT NULL DEFAULT 0
);
-- Candidate generation = "public Circles on these topics": serve it from one index.
CREATE INDEX idx_circles_access_topic ON circles(access, topic_slug);

-- Free-form tags. Not FK'd to topics on purpose: tags are user-entered and may drift
-- outside the taxonomy, even though today they all happen to be topic slugs.
CREATE TABLE circle_tags (
    circle_id  INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    tag        TEXT    NOT NULL,
    PRIMARY KEY (circle_id, tag)
);
CREATE INDEX idx_circle_tags_tag ON circle_tags(tag);

CREATE TABLE memberships (
    user_id    INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    circle_id  INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK (role IN ('member','leader')),
    joined_at  TEXT    NOT NULL,
    PRIMARY KEY (user_id, circle_id)        -- serves "which Circles is this user in?" (exclusion)
);
CREATE INDEX idx_memberships_circle_role ON memberships(circle_id, role);  -- leaders of a Circle

CREATE TABLE posts (
    id              INTEGER PRIMARY KEY,
    circle_id       INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    author_user_id  INTEGER NOT NULL REFERENCES users(id),
    body            TEXT    NOT NULL,
    reaction_count  INTEGER NOT NULL DEFAULT 0,
    comment_count   INTEGER NOT NULL DEFAULT 0,
    save_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL
);
-- Engagement roll-ups scan "posts for circle X in window": composite index makes it a range scan.
CREATE INDEX idx_posts_circle_created ON posts(circle_id, created_at);

-- Derived, per-Circle health features. Computed by app/features.py at seed time;
-- in production this is a materialised table refreshed by a scheduled job, so the
-- request path never aggregates raw posts.
CREATE TABLE circle_features (
    circle_id              INTEGER PRIMARY KEY REFERENCES circles(id) ON DELETE CASCADE,
    computed_as_of         TEXT    NOT NULL,
    days_since_activity    REAL    NOT NULL,
    posts_30d              INTEGER NOT NULL,
    engagement_per_post    REAL    NOT NULL,   -- (reactions + 2*comments + 2*saves) / post, last 30d
    is_full                INTEGER NOT NULL,
    is_inactive            INTEGER NOT NULL,
    health_score           REAL    NOT NULL    -- 0..1
);

CREATE TABLE dataset_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
