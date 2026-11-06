"""Print recommendations in the terminal.  Usage:  python -m app.cli 7 [--limit 5] [--debug]"""
from __future__ import annotations

import argparse
import json

from . import config
from .db import connect
from .seed import seed
from .service import recommend


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("user_id", type=int)
    p.add_argument("--limit", type=int, default=config.DEFAULT_LIMIT)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    if not config.DB_PATH.exists():
        seed()
    res = recommend(connect(), a.user_id, a.limit, a.debug)
    if a.json:
        print(json.dumps(res, indent=2))
        return
    print(f"User {res['user_id']} — strategy: {res['strategy']}")
    for r in res["recommendations"]:
        c = r["circle"]
        print(f"  {r['rank']}. #{c['id']} {c['name']}  [{r['match_type']}]")
        print(f"     {r['explanation']}")
        if r["similar_circles"]:
            print("     Similar: " + ", ".join(f"#{s['id']} {s['name']}" for s in r["similar_circles"]))
        if a.debug:
            print(f"     debug: {r['debug']}")
    if a.debug:
        print("  excluded:", res["debug"]["excluded"])


if __name__ == "__main__":
    main()
