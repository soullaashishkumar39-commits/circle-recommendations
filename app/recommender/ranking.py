"""Ranking pipeline:  eligibility -> score -> collapse duplicates -> backfill -> explain.

1. Eligibility (hard gates). A Circle is never recommended if the member is already in it,
   it's full, it's dormant, it's unlisted, it has no topic, or it's a life-stage Circle she
   hasn't said applies to her. Recommending a Circle she can't join, or one
   where nobody will answer her first post, is worse than recommending nothing.
2. Score = 0.65 * relevance + 0.35 * health  (plus small, named adjustments: friction, location fit).
   Relevance decides *what* she sees; health decides *which* of the relevant ones.
3. Collapse near-duplicates: keep the best Circle per primary topic; the rest ride along
   as `similar_circles` so the choice isn't hidden, just not repeated.
4. Backfill: if fewer relevant Circles than requested (or cold start), add the healthiest
   open, accessible Circles on topics not already shown, clearly labelled as discovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from ..repository import CircleCandidate, UserProfile
from .signals import Interest, build_interests

MIN_RELEVANCE = 0.15  # below this a "match" is too weak to claim as personal


@dataclass
class Match:
    topic: str
    kind: str          # "primary" | "tag"
    source: str        # interest source
    value: float


@dataclass
class Scored:
    circle: CircleCandidate
    matches: list[Match]
    relevance: float           # 0..1 normalised
    score: float
    bucket: str                # "personalized" | "discover"
    adjustments: dict[str, float] = field(default_factory=dict)
    similar: list[CircleCandidate] = field(default_factory=list)


@dataclass
class RankResult:
    strategy: str              # "personalized" | "cold_start"
    interests: dict[str, Interest]
    items: list[Scored]
    excluded: list[tuple[CircleCandidate, str]]


def _eligibility(c: CircleCandidate) -> str | None:
    if c.is_full:
        return "full"
    if c.is_inactive:
        return "inactive"
    if c.access != "public":
        return "unlisted"
    if c.topic is None:
        # Topic-less Circles here are identity/place communities ("The Latina Coalition",
        # "Women of the 405"). We have no consented signal to say who they're for and won't
        # infer identity from names, so they're left to search/browse, not algorithmic recs.
        return "no_topic"
    return None


def _matches(c: CircleCandidate, interests: dict[str, Interest]) -> list[Match]:
    out = []
    for topic, it in interests.items():
        if c.topic == topic:
            out.append(Match(topic, "primary", it.source, config.PRIMARY_TOPIC_MATCH * it.weight))
        elif topic in c.tags:
            out.append(Match(topic, "tag", it.source, config.TAG_MATCH * it.weight))
    return sorted(out, key=lambda m: -m.value)


def _relevance(matches: list[Match]) -> float:
    if not matches:
        return 0.0
    vals = [m.value for m in matches]
    raw = vals[0] + config.EXTRA_MATCH_BONUS * sum(vals[1:])
    return min(raw, config.RELEVANCE_CAP) / config.RELEVANCE_CAP


def _adjustments(c: CircleCandidate, user: UserProfile) -> dict[str, float]:
    """Small signed nudges on top of relevance/health. Each is named so debug output explains it."""
    a: dict[str, float] = {}
    if c.join_policy == "request":
        a["request_to_join"] = -config.REQUEST_TO_JOIN_PENALTY
    if not c.description or not c.cover_image_url:
        a["incomplete_circle_profile"] = -config.INCOMPLETE_PROFILE_PENALTY
    if c.topic in user.member_circle_topics:
        a["already_in_topic"] = -config.ALREADY_HAS_TOPIC_PENALTY

    # Location fit. Virtual Circles work for everyone; in-person ones only if she's nearby.
    remote = (user.location or "").strip().lower() == "remote"
    if c.format != "virtual":
        if c.local_members >= config.MIN_LOCAL_MEMBERS:
            a["members_nearby"] = config.LOCAL_MEMBER_BONUS_PER * min(c.local_members, config.LOCAL_MEMBER_BONUS_CAP)
        elif c.format == "in_person":
            a["in_person_location_unverified"] = -(
                config.REMOTE_IN_PERSON_PENALTY if remote else config.IN_PERSON_UNVERIFIED_PENALTY
            )
    return {k: round(v, 4) for k, v in a.items()}


def _collapse_duplicates(ranked: list[Scored], seen_topics: set[str]) -> list[Scored]:
    """Keep the top Circle per primary topic; attach the runners-up as `similar`."""
    leaders: dict[str, Scored] = {}
    out: list[Scored] = []
    for s in ranked:
        t = s.circle.topic
        if t in leaders:
            if len(leaders[t].similar) < 2:
                leaders[t].similar.append(s.circle)
            continue
        if t in seen_topics:
            continue
        leaders[t] = s
        out.append(s)
    return out


def rank(user: UserProfile, candidates: list[CircleCandidate], limit: int) -> RankResult:
    interests = build_interests(user)
    strategy = "personalized" if interests else "cold_start"

    eligible: list[CircleCandidate] = []
    excluded: list[tuple[CircleCandidate, str]] = []
    for c in candidates:
        reason = _eligibility(c)
        (excluded.append((c, reason)) if reason else eligible.append(c))

    personalized, discover = [], []
    for c in eligible:
        m = _matches(c, interests)
        if c.topic in config.LIFE_STAGE_TOPICS and not any(
            x.kind == "primary" and x.source in ("stated", "bio") for x in m
        ):
            excluded.append((c, "life_stage_not_self_identified"))
            continue
        rel = _relevance(m)
        adj = _adjustments(c, user)
        if rel >= MIN_RELEVANCE:
            score = config.RELEVANCE_WEIGHT * rel + config.HEALTH_WEIGHT * c.health_score + sum(adj.values())
            personalized.append(Scored(c, m, rel, round(score, 4), "personalized", adj))
        else:
            # Discovery: health first, plus a nudge toward Circles a newcomer can join today
            # without waiting on approval.
            bonus = 0.05 if c.join_policy == "open" else 0.0
            score = c.health_score + bonus + sum(adj.values())
            discover.append(Scored(c, [], 0.0, round(score, 4), "discover", adj))

    by_score = lambda s: (-s.score, s.circle.id)  # id tiebreak => deterministic output
    items = _collapse_duplicates(sorted(personalized, key=by_score), set())
    if len(items) < limit:
        shown = {s.circle.topic for s in items}
        items += _collapse_duplicates(sorted(discover, key=by_score), shown)

    return RankResult(strategy, interests, items[:limit], excluded)
