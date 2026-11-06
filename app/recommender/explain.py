"""Member-facing explanations, built only from signals the ranker actually used.

Templates rather than an LLM on purpose: every sentence is traceable to a field, there is
no risk of inventing facts about a Circle, output is deterministic and testable, and it
costs nothing per request. Each explanation = why it fits you + proof it's alive + how to join.
"""
from __future__ import annotations

from .ranking import Match, Scored

FORMAT_TEXT = {"virtual": "Meets virtually", "in_person": "Meets in person", "hybrid": "Meets in person and online"}


def _join_list(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _why_you(s: Scored, labels: dict[str, str], cold_start: bool) -> tuple[str, str]:
    c = s.circle
    topic = labels.get(c.topic or "", c.topic or "")
    if not s.matches:
        if cold_start:
            return "starter", f"One of the most active Circles on {topic} — a good place to start."
        return "popular", f"One of the most active Circles on {topic} right now."

    stated = [m for m in s.matches if m.source == "stated"]
    if stated:
        names = [labels[m.topic] for m in stated]
        if any(m.kind == "primary" for m in stated):
            if len(names) == 1:
                return "topic_match", f"Focused on {names[0]}, a topic you follow."
            return "topic_match", f"Covers {_join_list(names)} — topics you follow."
        return "tag_match", f"Also covers {_join_list(names)}, {'a topic' if len(names) == 1 else 'topics'} you follow."

    top: Match = s.matches[0]
    name = labels[top.topic]
    if top.source == "bio":
        return "bio_match", f"Focused on {name}, which lines up with what you shared in your profile."
    return "adjacent_match", f"Covers {name}, which also comes up in the Circles you're already part of."


def _proof_of_life(s: Scored) -> str:
    c = s.circle
    days = c.days_since_activity
    when = "today" if days < 1 else "yesterday" if days < 2 else f"{int(days)} days ago"
    if c.feed_posts_30d >= 10:
        return f"Very active: {c.feed_posts_30d} posts this month, last active {when}."
    return f"{c.feed_posts_30d} posts this month, last active {when}."


def _how_to_join(s: Scored, user_location: str | None) -> str:
    c = s.circle
    parts = [FORMAT_TEXT[c.format]]
    if "members_nearby" in s.adjustments:
        parts.append(f"{c.local_members} members based in {user_location}")
    parts.append("open to join" if c.join_policy == "open" else "request to join")
    if c.spots_left is not None and c.spots_left <= 5:
        parts.append(f"{c.spots_left} spot{'s' if c.spots_left != 1 else ''} left")
    return " · ".join(parts) + "."


def explain(
    s: Scored, labels: dict[str, str], cold_start: bool, user_location: str | None = None
) -> tuple[str, list[dict]]:
    code, why = _why_you(s, labels, cold_start)
    proof, join = _proof_of_life(s), _how_to_join(s, user_location)
    reasons = [
        {"code": code, "text": why},
        {"code": "active", "text": proof},
        {"code": "joinable", "text": join},
    ]
    if s.circle.leaders and s.circle.leaders[0].job_title:
        l = s.circle.leaders[0]
        reasons.append({"code": "leader", "text": f"Led by {l.first_name}, {l.job_title}."})
    return f"{why} {proof} {join}", reasons
