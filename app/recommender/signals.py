"""Turn a member's profile into weighted topic interests.

Sources, in order of trust:
  stated       topics she picked                                  (weight 1.0)
  bio          keywords in her own bio, mapped to the taxonomy    (weight 0.6)
  circle_tags  tags of Circles she already belongs to             (weight 0.4)

Deliberately NOT used: job title, company, industry. A title says what someone does,
not what she wants help with ("Product Manager" doesn't manage people), and inferring
needs from employer/industry is guesswork a member couldn't recognise in an explanation.
We also never infer identity (ethnicity, motherhood, etc.) from names or other fields.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .. import config
from ..repository import UserProfile

# Small, auditable phrase -> topic map. Each pattern is matched as a case-insensitive regex.
# Only phrases where the member is describing her own goal/situation. A production version
# would replace this with an embedding classifier over bio text, evaluated against stated interests.
BIO_KEYWORDS: dict[str, list[str]] = {
    "career-breaks": [r"career break", r"returning to work", r"back to work"],
    "managing-a-team": [r"first[- ]time manager", r"new manager", r"managing (a|my) team"],
    "leadership-skills": [r"leadership", r"leader(ship)? role", r"lead(ing)? a team"],
    "negotiation": [r"negotiat", r"comp conversation", r"salary", r"\braise\b"],
    "getting-promoted": [r"promot", r"next level", r"level up"],
    "confidence": [r"confiden"],
    "visibility-recognition": [r"executive presence", r"visibility", r"recogni[sz]"],
    "sponsorship-mentorship": [r"mentor", r"sponsor"],
    "public-speaking": [r"public speaking", r"presentations?\b", r"\bspeak(ing)?\b"],
    "stress-burnout": [r"burn ?out", r"stress"],
    "working-motherhood": [r"working mom", r"working mother", r"maternity"],
    "imposter-syndrome": [r"imposter", r"impostor"],
    "networking": [r"networking", r"\bnetwork\b"],
    "gender-bias": [r"pay equity", r"gender bias", r"\bbias\b"],
    "difficult-conversations": [r"difficult conversation", r"hard conversation"],
    "giving-feedback": [r"feedback"],
}
_COMPILED = {t: [re.compile(p, re.I) for p in pats] for t, pats in BIO_KEYWORDS.items()}


@dataclass(frozen=True)
class Interest:
    topic: str
    weight: float
    source: str  # "stated" | "bio" | "circle_tags"


def topics_from_bio(bio: str | None) -> list[str]:
    if not bio:
        return []
    return [t for t, pats in _COMPILED.items() if any(p.search(bio) for p in pats)]


def build_interests(user: UserProfile) -> dict[str, Interest]:
    """topic -> strongest Interest. A stated interest always wins over an inferred one."""
    w = config.SIGNAL_WEIGHTS
    out: dict[str, Interest] = {}

    def add(topic: str, source: str) -> None:
        cand = Interest(topic, w[source], source)
        if topic not in out or cand.weight > out[topic].weight:
            out[topic] = cand

    for t in user.stated_topics:
        add(t, "stated")
    for t in topics_from_bio(user.bio):
        add(t, "bio")
    # Tags of her existing Circles hint at adjacent interests. Her Circles' *primary* topics are
    # excluded on purpose — she already has a home for those, so they're a reason to diversify.
    for t in user.member_circle_tags - user.member_circle_topics:
        add(t, "circle_tags")
    return out
