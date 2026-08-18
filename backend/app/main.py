"""captain-mode backend: FastAPI + WebSocket lobby server."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .heroes import HEROES
from .lobby import LobbyManager
from . import db

app = FastAPI(title="Captain Mode Draft")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5199", "http://127.0.0.1:5199"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = LobbyManager()

# Interval for the stale-lobby cleanup cron (seconds). 5 minutes.
CLEANUP_INTERVAL = 5 * 60
# A waiting lobby with fewer than 2 captains is deleted once older than this.
STALE_MINUTES = 10


async def _cleanup_loop() -> None:
    """Periodically evict stale waiting lobbies (in-memory + DB)."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            evicted = manager.evict_stale(STALE_MINUTES)
            for code in evicted:
                await db.delete_lobby(code)
            await db.cleanup_stale_waiting(STALE_MINUTES)
        except Exception:
            pass


@app.on_event("startup")
async def startup() -> None:
    await db.migrate()
    asyncio.create_task(_cleanup_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    await db.close()


# ---------------- REST ----------------

class CreateBody(BaseModel):
    name: str
    color: int = 0
    lobby_name: str = ""
    turn_ms: int = 10_000
    reserve_ms: int = 60_000


class JoinBody(BaseModel):
    name: str
    seat_id: int | None = None


class ActionBody(BaseModel):
    action: str   # "ban" | "pick"
    hero_id: int


class ChooseBody(BaseModel):
    pick: str   # "radiant" | "dire" | "fp" | "sp"


@app.get("/api/heroes")
def get_heroes() -> list[dict]:
    return HEROES


@app.post("/api/lobby/create")
async def create_lobby(body: CreateBody) -> dict:
    turn_ms = max(1_000, min(body.turn_ms, 300_000))
    reserve_ms = max(0, min(body.reserve_ms, 3_600_000))
    lobby = manager.create(body.name.strip() or "Captain", body.color,
                           body.lobby_name.strip(), turn_ms, reserve_ms)
    seat = lobby.join(body.name.strip() or "Captain")
    await manager._persist_event(lobby, "create")
    return {"code": lobby.code, "seat_id": seat["seat_id"], "team": seat["team"],
            "color": seat["color"], "turn_ms": turn_ms, "reserve_ms": reserve_ms}


@app.post("/api/lobby/join")
async def join_lobby(code: str, body: JoinBody) -> dict:
    lobby = manager.get(code)
    if not lobby:
        return {"error": "Lobby tidak ditemukan"}
    seat = lobby.join(body.name.strip() or "Spectator", body.seat_id)
    await manager._persist_event(lobby, "join")
    return {"code": lobby.code, "seat_id": seat["seat_id"], "team": seat["team"],
            "color": seat.get("color", 0), "rejoined": bool(seat.get("rejoined"))}


@app.get("/api/lobby/state")
def lobby_state(code: str) -> dict:
    lobby = manager.get(code)
    if not lobby:
        return {"error": "Lobby tidak ditemukan"}
    return manager.room_state(lobby)


@app.post("/api/lobby/coin-flip")
async def coin_flip(code: str) -> dict:
    lobby = manager.get(code)
    if not lobby:
        return {"error": "Lobby tidak ditemukan"}
    res = lobby.flip_coin()
    if "error" in res:
        return res
    await lobby.broadcast({"type": "coin", "state": manager.room_state(lobby)})
    await lobby.broadcast({"type": "state", "state": manager.room_state(lobby)})
    return res


@app.post("/api/lobby/choose-side")
async def choose_side(code: str, seat_id: int, body: ChooseBody) -> dict:
    lobby = manager.get(code)
    if not lobby:
        return {"error": "Lobby tidak ditemukan"}
    res = lobby.choose_side(seat_id, body.pick)
    if "error" in res:
        return res
    # sides/first_pick may be finalized (step 2) — persist captain slots + broadcast
    if lobby.coin["phase"] == "done":
        await manager._persist_event(lobby, "join")
    await lobby.broadcast({"type": "state", "state": manager.room_state(lobby)})
    return res


@app.post("/api/lobby/start")
async def start_draft(code: str) -> dict:
    lobby = manager.get(code)
    if not lobby:
        return {"error": "Lobby tidak ditemukan"}
    if lobby.draft.started:
        return {"error": "Draft sudah dimulai"}
    if lobby.captains[0] is None or lobby.captains[1] is None:
        return {"error": "Butuh 2 captain untuk memulai draft"}
    if lobby.coin["phase"] != "done":
        return {"error": "Selesaikan coin flip dulu"}
    lobby.draft.start()
    await lobby.start_timer()
    await manager._persist_event(lobby, "start")
    await lobby.broadcast({"type": "state", "state": manager.room_state(lobby)})
    return {"ok": True}


@app.post("/api/lobby/action")
async def do_action(code: str, seat_id: int, body: ActionBody) -> dict:
    lobby = manager.get(code)
    if not lobby:
        return {"error": "Lobby tidak ditemukan"}
    team = lobby.captain_seat(seat_id)
    if team is None:
        return {"error": "Kamu bukan captain"}
    async with lobby._lock:
        step_before = lobby.draft.step
        result = lobby.draft.apply(team, body.action, body.hero_id)
        if result != "ok":
            return {"error": result}
        if not manager.is_valid_hero(body.hero_id):
            return {"error": "Hero tidak valid"}
        lobby.settle_reserve(team)
        await manager._persist_move(lobby, step_before, team, body.action, body.hero_id, "manual")
    await lobby.start_timer()
    await lobby.broadcast({"type": "state", "state": manager.room_state(lobby)})
    return {"ok": True}

@app.get("/api/history")
async def history_list(limit: int = 10, offset: int = 0,
                       search: str = "", status: str = "", sort: str = "desc") -> dict:
    return await db.list_history(min(max(limit, 1), 50), max(offset, 0),
                                 search.strip(), status, sort)


@app.get("/api/history/{code}")
async def history_detail(code: str) -> dict:
    detail = await db.get_history_detail(code)
    if not detail:
        return {"error": "Lobby tidak ditemukan di riwayat"}
    return detail


# ---------------- WebSocket ----------------

@app.websocket("/ws/{code}/{seat_id}")
async def ws_room(ws: WebSocket, code: str, seat_id: int):
    lobby = manager.get(code)
    if not lobby:
        await ws.close(code=4404, reason="Lobby not found")
        return
    await ws.accept()
    await lobby.attach(seat_id, ws)
    await ws.send_text(json.dumps({"type": "state", "state": manager.room_state(lobby)}))
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            mtype = data.get("type")
            if mtype == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            elif mtype == "action":
                team = lobby.captain_seat(seat_id)
                if team is None:
                    await ws.send_text(json.dumps({"type": "error", "error": "Kamu bukan captain"}))
                    continue
                try:
                    hero_id = int(data.get("hero_id", 0))
                except (TypeError, ValueError):
                    continue
                if not manager.is_valid_hero(hero_id):
                    await ws.send_text(json.dumps({"type": "error", "error": "Hero tidak valid"}))
                    continue
                async with lobby._lock:
                    step_before = lobby.draft.step
                    result = lobby.draft.apply(team, data.get("action"), hero_id)
                    if result != "ok":
                        await ws.send_text(json.dumps({"type": "error", "error": result}))
                        continue
                    lobby.settle_reserve(team)
                    await manager._persist_move(lobby, step_before, team, data.get("action"), hero_id, "manual")
                await lobby.start_timer()
                await lobby.broadcast({"type": "state", "state": manager.room_state(lobby)})
    except WebSocketDisconnect:
        pass
    finally:
        lobby.detach(seat_id, ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9002)
