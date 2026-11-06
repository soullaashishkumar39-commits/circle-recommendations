"""Runtime configuration. Everything tunable lives here so ranking weights are reviewable in one place."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("RECS_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.getenv("RECS_DB_PATH", ROOT / "circles.db"))

# The seed data is a frozen snapshot (latest activity ~2026-09-20). Measuring recency
# against the wall clock would mark every Circle inactive, so by default "now" is the
# snapshot time (max circles.last_activity_at), stored in dataset_meta at seed time.
# Override with an ISO timestamp, e.g. RECS_AS_OF=2026-09-21T00:00:00Z.
AS_OF_OVERRIDE = os.getenv("RECS_AS_OF")

DEFAULT_LIMIT = 5
MAX_LIMIT = 20

# --- Eligibility gates (hard filters) -------------------------------------------
INACTIVE_AFTER_DAYS = 45          # no activity in 45d => dormant; don't send new members there
MIN_POSTS_30D_FOR_ACTIVE = 1      # ...or nothing posted in the last 30 days

# --- Health score (0..1) ---------------------------------------------------------
# Sub-scores are each normalised against the 90th percentile of eligible Circles,
# log-scaled so one hyperactive Circle doesn't flatten everyone else.
HEALTH_WEIGHTS = {
    "posts": 0.35,        # members are actually showing up and sharing
    "chat": 0.20,         # conversation between posts (aggregate only, no message text)
    "engagement": 0.25,   # replies/saves per post: is anyone responding?
    "recency": 0.20,      # how recently something happened
}
RECENCY_HALF_LIFE_DAYS = 10

# --- Relevance -------------------------------------------------------------------
# How much we trust each source of interest signal.
SIGNAL_WEIGHTS = {
    "stated": 1.0,        # topics the member picked
    "bio": 0.6,           # keywords in her own bio
    "circle_tags": 0.3,   # tags of Circles she already belongs to
}
PRIMARY_TOPIC_MATCH = 1.0         # Circle's main topic == interest
TAG_MATCH = 0.5                   # interest appears only in the Circle's tags
EXTRA_MATCH_BONUS = 0.25          # each additional matched interest adds this fraction
RELEVANCE_CAP = 1.5

# --- Final blend -----------------------------------------------------------------
RELEVANCE_WEIGHT = 0.65
HEALTH_WEIGHT = 0.35
REQUEST_TO_JOIN_PENALTY = 0.03    # small friction cost vs. open Circles
INCOMPLETE_PROFILE_PENALTY = 0.03 # Circle missing description or cover image
ALREADY_HAS_TOPIC_PENALTY = 0.15  # she's already in a Circle on this exact topic
REMOTE_IN_PERSON_PENALTY = 0.10   # member says "Remote"; in-person Circle is a worse fit

# --- Life-stage Circles ---------------------------------------------------------
# Circles centred on a life circumstance are only recommended when the member has said
# (stated topic or her own bio) that it applies to her. A tag overlap or popularity is not
# enough: suggesting "Working Mothers United" to someone who never mentioned children
# feels presumptuous at best.
LIFE_STAGE_TOPICS = {"working-motherhood", "career-breaks", "being-the-only-one"}

# --- Location fit (in-person / hybrid) -------------------------------------------
# Circles have no location field, so "where do current members live?" is the proxy for
# "could she actually attend?". Graded so more nearby members => more viable meetups.
MIN_LOCAL_MEMBERS = 2
LOCAL_MEMBER_BONUS_PER = 0.02
LOCAL_MEMBER_BONUS_CAP = 4        # bonus tops out at 4 nearby members (+0.08)
IN_PERSON_UNVERIFIED_PENALTY = 0.05  # in-person only, and we can't see anyone nearby
