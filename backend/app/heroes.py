"""Hero data loading — single source of truth for hero pool."""

from __future__ import annotations

import json
from pathlib import Path

CDN = "https://cdn.cloudflare.steamstatic.com"

HEROES: list[dict] = json.loads(
    (Path(__file__).parent / "data" / "heroes.json").read_text(encoding="utf-8")
)
HERO_BY_ID: dict[int, dict] = {h["id"]: h for h in HEROES}


def hero_card(hero_id: int) -> dict:
    h = HERO_BY_ID.get(hero_id)
    if h is None:
        return {"id": hero_id, "name": "?", "attr": "all", "img": ""}
    return {"id": h["id"], "name": h["name"], "attr": h["attr"], "img": h["img"]}
