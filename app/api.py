"""HTTP API.  Run:  uvicorn app.api:app --reload"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import config
from .db import connect
from .seed import seed
from .service import UserNotFound, recommend


class CircleOut(BaseModel):
    id: int
    name: str
    slug: str
    topic: Optional[str]
    topic_label: Optional[str]
    format: str
    join_policy: str
    member_count: int
    max_members: Optional[int]
    spots_left: Optional[int]
    cover_image_url: Optional[str]


class Reason(BaseModel):
    code: str
    text: str


class SimilarCircle(BaseModel):
    id: int
    name: str


class Recommendation(BaseModel):
    rank: int
    circle: CircleOut
    explanation: str
    reasons: list[Reason]
    match_type: str
    similar_circles: list[SimilarCircle]
    debug: Optional[dict] = None


class RecommendationsResponse(BaseModel):
    user_id: int
    strategy: str
    as_of: str
    recommendations: list[Recommendation]
    prompt: Optional[str] = None
    debug: Optional[dict] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.DB_PATH.exists():
        seed()
    app.state.conn = connect()
    yield
    app.state.conn.close()


app = FastAPI(
    title="Lean In Circle Recommendations",
    description="Ranked Circles for a member, each with a member-facing reason.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get(
    "/users/{user_id}/recommendations",
    response_model=RecommendationsResponse,
    response_model_exclude_unset=True,
)
def get_recommendations(
    user_id: int,
    limit: int = Query(config.DEFAULT_LIMIT, ge=1, le=config.MAX_LIMIT),
    debug: bool = Query(False, description="Include score breakdown and excluded Circles"),
):
    try:
        return recommend(app.state.conn, user_id, limit, debug)
    except UserNotFound:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
