"""Scenario + invariant tests.  Run:  pytest -q"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import connect
from app.seed import seed
from app.service import UserNotFound, recommend

ALL_USERS = [u["id"] for u in json.loads((config.DATA_DIR / "users.json").read_text())]
CIRCLES = {c["id"]: c for c in json.loads((config.DATA_DIR / "circles.json").read_text())}


@pytest.fixture(scope="session")
def conn(tmp_path_factory):
    db = seed(tmp_path_factory.mktemp("db") / "test.db")
    c = connect(db)
    yield c
    c.close()


def ids(res):
    return [r["circle"]["id"] for r in res["recommendations"]]


# ---------------------------------------------------------------- planted scenarios

def test_cold_start_user_42(conn):
    res = recommend(conn, 42, 5, debug=True)
    assert res["strategy"] == "cold_start"
    assert len(res["recommendations"]) == 5
    assert all(r["match_type"] == "discover" for r in res["recommendations"])
    assert "prompt" in res  # nudge her to add interests
    # A spread of topics, all joinable without approval.
    assert len({r["circle"]["topic"] for r in res["recommendations"]}) == 5
    assert all(r["circle"]["join_policy"] == "open" for r in res["recommendations"])


def test_obvious_matches_user_7(conn):
    res = recommend(conn, 7, 5)
    assert set(ids(res)[:2]) == {5, 6}  # Women Who Lead, Speak Up Circle
    assert "a topic you follow" in res["recommendations"][0]["explanation"] or "topics you follow" in res["recommendations"][0]["explanation"]


def test_duplicates_user_15(conn):
    res = recommend(conn, 15, 10)
    shown = [i for i in ids(res) if i in (10, 11, 12)]
    assert len(shown) == 1, "exactly one of the near-identical Negotiation Circles is shown"
    rec = next(r for r in res["recommendations"] if r["circle"]["id"] == shown[0])
    assert {s["id"] for s in rec["similar_circles"]} == {10, 11, 12} - {shown[0]}
    assert res["recommendations"][0]["circle"]["topic"] in ("negotiation", "confidence")


def test_full_and_inactive_user_23(conn):
    res = recommend(conn, 23, 10, debug=True)
    assert ids(res)[0] == 22  # Level Up Collective
    assert 20 not in ids(res) and 21 not in ids(res)
    excluded = {e["id"]: e["reason"] for e in res["debug"]["excluded"]}
    assert excluded[20] == "full"
    assert excluded[21] == "inactive"


# ---------------------------------------------------------------- invariants for every user

@pytest.mark.parametrize("user_id", ALL_USERS)
def test_every_user_gets_sensible_recs(conn, user_id):
    res = recommend(conn, user_id, 5)
    recs = res["recommendations"]
    assert len(recs) == 5
    member_of = {r["circle_id"] for r in conn.execute("SELECT circle_id FROM memberships WHERE user_id=?", (user_id,))}
    topics = [r["circle"]["topic"] for r in recs]
    assert len(topics) == len(set(topics)), "no two results on the same primary topic"
    for r in recs:
        c = CIRCLES[r["circle"]["id"]]
        assert c["id"] not in member_of
        assert c["access"] == "public"
        assert c["max_members"] is None or c["member_count"] < c["max_members"]
        assert c["feed_posts_30d"] > 0
        assert r["explanation"] and len(r["explanation"]) < 260
    assert [r["rank"] for r in recs] == [1, 2, 3, 4, 5]


def test_life_stage_circles_need_self_identification(conn):
    # User 23 never mentioned motherhood or a career break.
    res = recommend(conn, 23, 20)
    assert not {19, 29, 2, 33} & set(ids(res))


def test_deterministic(conn):
    assert recommend(conn, 15, 5) == recommend(conn, 15, 5)


def test_unknown_user(conn):
    with pytest.raises(UserNotFound):
        recommend(conn, 99999, 5)


# ---------------------------------------------------------------- HTTP layer

def test_api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "api.db")
    from app.api import app

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        r = client.get("/users/7/recommendations")
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == 7 and len(body["recommendations"]) == config.DEFAULT_LIMIT
        assert "debug" not in body["recommendations"][0]
        assert "debug" in client.get("/users/7/recommendations?debug=true").json()
        assert client.get("/users/99999/recommendations").status_code == 404
        assert client.get("/users/7/recommendations?limit=0").status_code == 422
        assert client.get("/users/7/recommendations?limit=21").status_code == 422
