"""Lobby + WebSocket connection manager for captain-mode.

In-memory only — restart loses lobbies. No auth; a 6-char lobby code is the
only secret. First two seats claim captain slots; anyone else is spectator.

Timer ownership: each Lobby runs exactly ONE per-turn timer task, guarded by a
monotonic epoch counter so a stale auto-fire can never act on a newer turn.
"""

from __future__ import annotations

import asyncio
import json
import random
import string
import time
from typing import Any

from fastapi import WebSocket

from .draft import TURNS, TURN_MS, DraftState, draft_turn_blocks
from .heroes import HEROES, HERO_BY_ID, hero_card

CODE_ALPHABET = string.ascii_uppercase + string.digits


def gen_code(length: int = 6) -> str:
    return "".join(random.choices(CODE_ALPHABET, k=length))


class Lobby:
    def __init__(self, code: str, host_name: str, host_color: int,
                 lobby_name: str = "", turn_ms: int = TURN_MS,
                 reserve_ms: int = 60_000) -> None:
        self.code = code
        self.host_name = host_name
        self.lobby_name = lobby_name
        self.host_color = host_color
        self.created_ts = time.time()
        self.turn_ms = max(1_000, min(turn_ms, 300_000))       # 1s..5min per turn
        self.reserve_ms = max(0, min(reserve_ms, 3_600_000))   # 0..60min per team
        self.reserve_left: list[int] = [self.reserve_ms, self.reserve_ms]  # per team
        self.draft = DraftState()
        self.captains: list[dict | None] = [None, None]  # team 0 = first-pick side
        self.sides: list[dict | None] = [None, None]     # [0] = Radiant, [1] = Dire
        self.spectators: dict[int, dict] = {}            # seat_id -> info
        self.coin: dict = {
            "phase": "pending",        # pending | choose | choose2 | done
            "winner_seat": None,
            "winner_name": None,
            "winner_team": None,       # captain's seat position (0 or 1) from join order
            "side_pick": None,         # 'radiant' | 'dire' — decided by winner or loser
            "pick_pick": None,         # 'fp' | 'sp' — decided by winner or loser
            "first_pick": None,        # seat_id of the captain with FIRST PICK
            "_winner_axis": None,      # 'side' | 'pick' — axis the winner chose in step 1
        }
        self._seat_counter = 1
        self._sockets: dict[int, WebSocket] = {}
        self._lock = asyncio.Lock()
        self._timer_task: asyncio.Task | None = None
        self._timer_epoch = 0
        self._deadline: float | None = None
        self._reserve_started_at: float | None = None
        self._auto_cb = None  # set by LobbyManager: async (Lobby) -> None

    # ---------- seats ----------
    def _new_seat(self) -> int:
        seat = self._seat_counter
        self._seat_counter += 1
        return seat

    def join(self, name: str, seat_id: int | None = None) -> dict:
        """Join or REJOIN the lobby.

        A returning player gets their ORIGINAL seat back. Two ways:
          1. seat_id — the FE remembers its old seat in localStorage (cm_seat)
             and sends it; if that seat is still a registered captain it is
             reclaimed, regardless of name changes/trailing spaces.
          2. name — captains are ALWAYS reclaimed by matching name (takeover):
             a returning captain whose old tab still holds a live socket would
             otherwise fall through to a fresh spectator seat. Name is the
             identity in this no-auth app.
        Only when neither matches do we allocate a new seat.
        """
        name = name.strip()
        if not name:
            name = "Spectator"

        # 0) Rejoin by remembered seat (captain only, name must match too — a
        #    bare seat_id like 1 is the first captain slot in EVERY lobby, so
        #    reclaiming it without a name match could steal someone else's seat).
        if seat_id is not None:
            cap = self._captain_by_seat(seat_id)
            if cap and cap["name"].casefold() == name.casefold():
                return {**cap, "rejoined": True}

        # 1) Rejoin by name: captain slot ALWAYS reclaimed (takeover). Case-
        #    insensitive so "Alfia" vs "alfia" still reclaims the seat.
        for cap in self.captains:
            if cap and cap["name"].casefold() == name.casefold():
                return {**cap, "rejoined": True}
        for seat_id, info in self.spectators.items():
            if info["name"].casefold() == name.casefold() and seat_id not in self._sockets:
                return {**info, "rejoined": True}

        # 2) Fresh captain slot (first two seats).
        for team, cap in enumerate(self.captains):
            if cap is None:
                seat = self._new_seat()
                self.captains[team] = {
                    "seat_id": seat, "name": name,
                    "team": team, "color": self.host_color if team == 0 else (255 - self.host_color),
                }
                self._seat_to_side(seat)
                return {**self.captains[team], "rejoined": False}

        # 3) Spectator.
        seat = self._new_seat()
        info = {"seat_id": seat, "name": name, "team": None}
        self.spectators[seat] = info
        return {**info, "rejoined": False}

    def _seat_to_side(self, seat_id: int) -> None:
        """Claim the first free side slot (Radiant first, then Dire)."""
        cap = self._captain_by_seat(seat_id)
        if not cap:
            return
        for i, s in enumerate(self.sides):
            if s is None:
                self.sides[i] = {"seat_id": seat_id, "name": cap["name"], "team": i}
                break

    def _captain_by_seat(self, seat_id: int) -> dict | None:
        for cap in self.captains:
            if cap and cap["seat_id"] == seat_id:
                return cap
        return None

    def captain_seat(self, seat_id: int) -> int | None:
        """ENGINE team for a captain's seat (0 = first-pick side, 1 = second-pick).

        Resolved from the finalized sides + first_pick: the first-pick captain is
        engine team 0. Used by the action endpoints to validate turns — the engine
        TURNS list is always in first-pick/second-pick order.
        """
        fp_seat = self.coin.get("first_pick")
        if fp_seat is not None:
            return 0 if seat_id == fp_seat else (1 if self._is_captain(seat_id) else None)
        # fallback before coin done: sides not set yet — use seating order
        for team, cap in enumerate(self.captains):
            if cap and cap["seat_id"] == seat_id:
                return team
        return None

    def _is_captain(self, seat_id: int) -> bool:
        return any(c and c["seat_id"] == seat_id for c in self.captains)

    # ---------- coin flip ----------
    def flip_coin(self) -> dict:
        """Flip the coin; winner claims the choice. Returns state."""
        if self.draft.started:
            return {"error": "Draft sudah dimulai"}
        caps = [c for c in self.captains if c]
        if len(caps) < 2:
            return {"error": "Butuh 2 captain untuk coin flip"}
        if self.coin["phase"] == "done":
            return {"error": "Coin flip sudah selesai"}
        winner = self._random_choice(caps)
        self.coin.update({
            "phase": "choose",
            "winner_seat": winner["seat_id"],
            "winner_name": winner["name"],
            "winner_team": winner["team"],
            "side_pick": None,
            "pick_pick": None,
            "first_pick": None,
            "_winner_axis": None,
        })
        return {"ok": True, "winner_seat": winner["seat_id"], "winner_name": winner["name"], "winner_team": winner["team"]}

    def _random_choice(self, caps: list[dict]) -> dict:
        """Deterministic-ish pick for tests; real randomness from LobbyManager RNG."""
        return caps[self._rng() % len(caps)]

    def _rng(self) -> int:
        """Randomness hook — LobbyManager injects a seeded RNG."""
        if hasattr(self, "_rng_state"):
            return self._rng_state
        return int(time.time() * 1000) % 1000000

    def choose_side(self, seat_id: int, pick: str) -> dict:
        """Two-step coin resolution (Dota model).

        Step 1 — winner picks ONE axis: side ('radiant'|'dire') OR pick order
        ('fp'|'sp'). Step 2 — the LOSER picks from the 2 options on the other
        axis. Once both are decided the sides + first-pick mapping is final.
        """
        if self.draft.started:
            return {"error": "Draft sudah dimulai"}
        if pick not in ("radiant", "dire", "fp", "sp"):
            return {"error": "Pilihan tidak valid"}
        winner_seat = self.coin["winner_seat"]
        if self.coin["phase"] == "choose":
            if winner_seat != seat_id:
                return {"error": "Bukan giliranmu memilih"}
            self.coin["phase"] = "choose2"
            self.coin["_winner_axis"] = "side" if pick in ("radiant", "dire") else "pick"
            if pick in ("radiant", "dire"):
                self.coin["side_pick"] = pick
            else:
                self.coin["pick_pick"] = pick
            return {"ok": True}
        if self.coin["phase"] == "choose2":
            if winner_seat == seat_id:
                return {"error": "Pemenang sudah memilih"}
            loser_seat = self._loser_seat()
            if loser_seat is None or loser_seat != seat_id:
                return {"error": "Bukan giliranmu memilih"}
            # loser picks on the OTHER axis (winner chose side -> pick order, vice versa)
            if self.coin["side_pick"] is not None:
                # winner chose side -> loser must pick pick order (fp/sp)
                if pick in ("radiant", "dire"):
                    return {"error": "Pemenang sudah memilih sisi — pilih urutan pick"}
                self.coin["pick_pick"] = pick
            else:
                # winner chose pick order -> loser must pick side (radiant/dire)
                if pick in ("fp", "sp"):
                    return {"error": "Pemenang sudah memilih urutan pick — pilih sisi"}
                self.coin["side_pick"] = pick
            self.coin["phase"] = "done"
            self._finalize_sides()
            return {"ok": True}
        return {"error": "Belum waktunya memilih sisi"}

    def _loser_seat(self) -> int | None:
        """Seat of the captain who did NOT win the coin flip."""
        for cap in self.captains:
            if cap and cap["seat_id"] != self.coin["winner_seat"]:
                return cap["seat_id"]
        return None

    def _finalize_sides(self) -> None:
        """Assign Radiant/Dire + first-pick based on BOTH decisions.

        sides[0] = Radiant, sides[1] = Dire (UI columns).
        first_pick = seat_id of the captain whose team drafts first.

        Axis ownership: the winner's step-1 pick claims one axis; the loser's
        step-2 pick is on the other axis (recorded in coin._winner_axis).
          side_owner = winner if winner took side, else loser
          pick_owner = the other one
          radiant captain = side_owner if side_pick=='radiant' else other(side_owner)
          first-pick captain = pick_owner if pick_pick=='fp' else other(pick_owner)
        """
        w = self.coin["winner_seat"]
        l = self._loser_seat()
        if w is None or l is None:
            return
        winner_took_side = self.coin.get("_winner_axis") == "side"
        side_owner = w if winner_took_side else l
        pick_owner = l if winner_took_side else w
        side_pick = self.coin.get("side_pick")
        pick_pick = self.coin.get("pick_pick")
        if side_pick is None or pick_pick is None:
            return
        radiant = side_owner if side_pick == "radiant" else self._other_cap(side_owner)
        fp_seat = pick_owner if pick_pick == "fp" else self._other_cap(pick_owner)
        if radiant is None or fp_seat is None:
            return
        self.sides[0] = self._cap_slot(radiant, 0)
        dire_seat = self._other_cap(radiant)
        self.sides[1] = self._cap_slot(dire_seat, 1)
        self.coin["first_pick"] = fp_seat

    def _cap_slot(self, seat_id: int, team: int = 0) -> dict | None:
        cap = self._captain_by_seat(seat_id)
        return {"seat_id": cap["seat_id"], "name": cap["name"], "team": team} if cap else None

    def _other_cap(self, seat_id: int) -> int | None:
        for cap in self.captains:
            if cap and cap["seat_id"] != seat_id:
                return cap["seat_id"]
        return None

    def kick_seat(self, seat_id: int) -> None:
        for team, cap in enumerate(self.captains):
            if cap and cap["seat_id"] == seat_id:
                self.captains[team] = None
                self.sides[team] = None
                return
        self.spectators.pop(seat_id, None)

    # ---------- timers ----------
    async def start_timer(self) -> None:
        """Cancel any pending auto-fire and arm a fresh one for the new turn."""
        self.clear_timer_task()
        self._timer_epoch += 1
        self._reserve_started_at = None
        self._deadline = time.time() + self.turn_ms / 1000
        self._timer_task = asyncio.create_task(self._auto_cb(self))

    def settle_reserve(self, team: int) -> None:
        """Charge the acting team's reserve for time spent past the base turn."""
        if self._reserve_started_at is None:
            return
        used = int((time.time() - self._reserve_started_at) * 1000)
        self.reserve_left[team] = max(0, self.reserve_left[team] - used)
        self._reserve_started_at = None

    def clear_timer_task(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    def clear_timer(self) -> None:
        self.clear_timer_task()
        self._deadline = None

    # ---------- ws plumbing ----------
    async def attach(self, seat_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._sockets[seat_id] = ws

    def detach(self, seat_id: int, ws: WebSocket | None = None) -> None:
        # Only remove the socket if it is the one that was attached — with two
        # tabs sharing a seat, closing one tab must not kill the other's socket.
        if ws is None or self._sockets.get(seat_id) is ws:
            self._sockets.pop(seat_id, None)

    async def send(self, seat_id: int, message: dict) -> None:
        ws = self._sockets.get(seat_id)
        if ws:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                pass

    async def broadcast(self, message: dict, exclude_seat: int | None = None) -> None:
        payload = json.dumps(message)
        dead: list[int] = []
        for seat_id, ws in list(self._sockets.items()):
            if seat_id == exclude_seat:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(seat_id)
        for seat_id in dead:
            self.detach(seat_id)


class LobbyManager:
    def __init__(self) -> None:
        self._lobbies: dict[str, Lobby] = {}
        self._random = random.Random()

    def create(self, host_name: str, color: int, lobby_name: str = "",
               turn_ms: int = TURN_MS, reserve_ms: int = 60_000) -> Lobby:
        code = gen_code()
        while code in self._lobbies:
            code = gen_code()
        lobby = Lobby(code, host_name, color, lobby_name, turn_ms, reserve_ms)
        lobby._auto_cb = self._auto_fire
        lobby._rng = lambda: self._random.randrange(1_000_000)
        self._lobbies[code] = lobby
        return lobby

    async def _persist_event(self, lobby: Lobby, event: str) -> None:
        """Persist hook — awaited from endpoints (create/join/start/finished)."""
        from . import db
        try:
            # DB captain0/captain1 = Radiant/Dire (UI columns), from sides when finalized
            if lobby.sides[0]:
                c0 = lobby.sides[0]["name"]
                c1 = lobby.sides[1]["name"] if lobby.sides[1] else None
            else:
                c0 = lobby.captains[0]["name"] if lobby.captains[0] else None
                c1 = lobby.captains[1]["name"] if lobby.captains[1] else None
            if event == "create":
                await db.persist_lobby(lobby.code, lobby.host_name, lobby.host_color,
                                       c0, c1, "waiting", lobby.lobby_name,
                                       lobby.turn_ms, lobby.reserve_ms)
            elif event == "join":
                await db.persist_lobby(lobby.code, lobby.host_name, lobby.host_color,
                                       c0, c1, "waiting", lobby.lobby_name,
                                       lobby.turn_ms, lobby.reserve_ms)
            elif event == "start":
                await db.mark_started(lobby.code, c0, c1)
            elif event == "finished":
                await db.mark_finished(lobby.code)
        except Exception:
            pass

    def evict_stale(self, min_age_minutes: int = 10) -> list[str]:
        """Remove in-memory lobbies stuck waiting with <2 captains, older than
        min_age. Returns evicted codes."""
        now = time.time()
        evicted: list[str] = []
        for code, lobby in list(self._lobbies.items()):
            if lobby.draft.started or lobby.draft.finished:
                continue
            caps = sum(1 for c in lobby.captains if c)
            if caps < 2 and not lobby._sockets and (now - lobby.created_ts) > min_age_minutes * 60:
                self.remove(code)
                evicted.append(code)
        return evicted

    def get(self, code: str) -> Lobby | None:
        return self._lobbies.get(code)

    def remove(self, code: str) -> None:
        lobby = self._lobbies.pop(code, None)
        if lobby:
            lobby.clear_timer()

    def room_state(self, lobby: Lobby) -> dict[str, Any]:
        d = lobby.draft
        # Engine team 0 = FIRST-PICK side, team 1 = second-pick side. UI columns are
        # Radiant (index 0) | Dire (index 1). Map engine -> UI so the timeline always
        # shows Radiant left / Dire right regardless of who got first pick.
        fp_seat = lobby.coin.get("first_pick")
        ui_of_engine = [0, 1]  # default: engine 0 = Radiant (index 0)
        if fp_seat is not None:
            # engine 0 is the first-pick captain's side -> find which UI column that is
            fp_col = next((i for i, s in enumerate(lobby.sides)
                           if s and s["seat_id"] == fp_seat), 0)
            ui_of_engine = [fp_col, 1 - fp_col]
        e0, e1 = ui_of_engine

        def ui_bans(bucket: list[list[int]]) -> list[list[dict]]:
            out: list[list[dict]] = [[], []]
            out[e0] = [hero_card(i) for i in bucket[0]]
            out[e1] = [hero_card(i) for i in bucket[1]]
            return out

        return {
            "code": lobby.code,
            "host": lobby.host_name,
            "lobby_name": lobby.lobby_name,
            "captains": [
                c and {"seat_id": c["seat_id"], "name": c["name"], "color": c["color"]}
                for c in lobby.captains
            ],
            "sides": [
                s and {"seat_id": s["seat_id"], "name": s["name"], "team": s["team"]}
                for s in lobby.sides
            ],
            "coin": dict(lobby.coin),
            "can_start": (
                lobby.coin["phase"] == "done"
                and lobby.sides[0] is not None and lobby.sides[1] is not None
            ),
            "spectator_count": len(lobby.spectators),
            "draft": {
                "started": d.started,
                "finished": d.finished,
                "phase": d.phase,
                "team": ui_of_engine[d.current_team] if d.started else 0,
                "step": d.step,
                "total_steps": len(TURNS),
                "phase_label": ("Pick Phase" if d.phase == "pick" else "Ban Phase") if not d.finished else "Finished",
                "turn_blocks": draft_turn_blocks(),
                "turn_sequence": [{"phase": p, "team": ui_of_engine[t]} for p, t in TURNS],
                "bans": ui_bans(d.bans),
                "picks": ui_bans(d.picks),
                # deadline 0 once finished so the UI shows 0 instead of a stale countdown
                "deadline": lobby._deadline if not d.finished else 0,
                "turn_ms": lobby.turn_ms,
                "reserve_ms": lobby.reserve_ms,
                "reserve_left": list(lobby.reserve_left),
            },
        }

    async def _auto_fire(self, lobby: Lobby) -> None:
        """Timer callback: sleep, then auto-resolve the CURRENT turn.

        Two-phase: after the base turn_ms expires the acting team's reserve is
        consumed (deadline extends by remaining reserve). Only when the team's
        reserve is also exhausted does the draft auto-pick a random hero.
        """
        epoch = lobby._timer_epoch
        await asyncio.sleep(lobby.turn_ms / 1000)
        async with lobby._lock:
            if lobby._timer_epoch != epoch or lobby._deadline is None or lobby.draft.finished:
                return
            d = lobby.draft
            team = d.current_team
            # ---- phase 1: base turn expired -> enter reserve ----
            if lobby._reserve_started_at is None:
                lobby._reserve_started_at = time.time()
                lobby._deadline = time.time() + lobby.reserve_left[team] / 1000
                lobby._timer_epoch += 1
                lobby._timer_task = asyncio.create_task(self._auto_fire(lobby))
                await lobby.broadcast({"type": "state", "state": self.room_state(lobby)})
                return
            # ---- phase 2: reserve expired -> auto-pick ----
            lobby.settle_reserve(team)
            step_before = d.step
            hero = self._random_available(lobby)
            if hero is None:
                lobby._deadline = None
                return
            result = d.apply(team, d.phase, hero)
            if result != "ok":
                lobby._deadline = None
                return
            await self._persist_move(lobby, step_before, team, d.phase, hero, "auto")
            lobby._timer_task = None
            if not d.finished:
                await lobby.start_timer()
            await lobby.broadcast({"type": "auto", "team": team, "phase": d.phase, "hero_id": hero})
            await lobby.broadcast({"type": "state", "state": self.room_state(lobby)})

    async def _persist_move(self, lobby: Lobby, step: int, team: int, phase: str, hero_id: int, source: str) -> None:
        from . import db
        try:
            hero = HERO_BY_ID.get(hero_id)
            name = hero["name"] if hero else f"hero-{hero_id}"
            await db.persist_move(lobby.code, step, team, phase, hero_id, name, source)
            if lobby.draft.finished:
                await db.mark_finished(lobby.code)
        except Exception:
            pass

    def _random_available(self, lobby: Lobby) -> int | None:
        taken = set(
            lobby.draft.bans[0] + lobby.draft.bans[1]
            + lobby.draft.picks[0] + lobby.draft.picks[1]
        )
        pool = [h["id"] for h in HEROES if h["id"] not in taken]
        return self._random.choice(pool) if pool else None

    def is_valid_hero(self, hero_id: int) -> bool:
        return hero_id in HERO_BY_ID
