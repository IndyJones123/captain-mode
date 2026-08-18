"""PostgreSQL persistence + migration runner for captain-mode.

Local PostgreSQL 17 at localhost:5432, database `captain_mode`, user `captain`.
Migrations live in backend/migrations/ as *.sql files (PostgreSQL dialect),
applied in filename order at startup, tracked in schema_migrations.
All writes are best-effort (fire-and-forget) so they never block the WS hot path.
"""

from __future__ import annotations

import os
from pathlib import Path

import asyncpg

BASE_DIR = Path(__file__).resolve().parent.parent   # backend/
MIGRATIONS_DIR = BASE_DIR / "migrations"

# Connection config — overridable via env for tests
PG_DSN = os.environ.get(
    "CM_PG_DSN",
    "postgresql://captain:captain@localhost:5432/captain_mode",
)

_pool: asyncpg.Pool | None = None


async def connect() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=5)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def migrate() -> list[str]:
    """Apply pending *.sql migrations in filename order. Returns applied names."""
    pool = await connect()
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        rows = await conn.fetch("SELECT name FROM schema_migrations")
        applied = {r["name"] for r in rows}
        done: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO schema_migrations (name) VALUES ($1)", path.name
            )
            done.append(path.name)
    return done


# ---------------- helpers ----------------

async def persist_lobby(code: str, host_name: str, host_color: int,
                        captain0: str | None, captain1: str | None, status: str,
                        lobby_name: str = "", turn_ms: int = 10000,
                        reserve_ms: int = 60000) -> None:
    try:
        pool = await connect()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO lobbies (code, host_name, host_color, status, captain0, captain1, lobby_name, turn_ms, reserve_ms, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
                   ON CONFLICT (code) DO UPDATE SET
                    status = EXCLUDED.status,
                    captain0 = COALESCE(EXCLUDED.captain0, lobbies.captain0),
                    captain1 = COALESCE(EXCLUDED.captain1, lobbies.captain1),
                    lobby_name = EXCLUDED.lobby_name,
                    turn_ms = EXCLUDED.turn_ms,
                    reserve_ms = EXCLUDED.reserve_ms""",
                code, host_name, host_color, status, captain0, captain1, lobby_name,
                turn_ms, reserve_ms,
            )
    except Exception:
        pass


async def mark_started(code: str, captain0: str | None, captain1: str | None) -> None:
    try:
        pool = await connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE lobbies SET status='running', started_at=now(), captain0=$2, captain1=$3 WHERE code=$1",
                code, captain0, captain1,
            )
    except Exception:
        pass


async def persist_move(code: str, step: int, team: int, phase: str,
                       hero_id: int, hero_name: str, source: str) -> None:
    try:
        pool = await connect()
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO draft_moves (code, step, team, phase, hero_id, hero_name, source)"
                    " VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    code, step, team, phase, hero_id, hero_name, source,
                )
            except asyncpg.ForeignKeyViolationError:
                # lobby row may not exist yet (fire-and-forget create) — upsert stub then retry
                await conn.execute(
                    """INSERT INTO lobbies (code, host_name, host_color, status)
                       VALUES ($1, '', 0, 'waiting')
                       ON CONFLICT (code) DO NOTHING""", code
                )
                await conn.execute(
                    "INSERT INTO draft_moves (code, step, team, phase, hero_id, hero_name, source)"
                    " VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    code, step, team, phase, hero_id, hero_name, source,
                )
    except Exception:
        pass


async def mark_finished(code: str) -> None:
    try:
        pool = await connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE lobbies SET status='finished', finished_at=now() WHERE code=$1", code
            )
    except Exception:
        pass


async def list_history(limit: int = 20, offset: int = 0,
                       search: str = "", status_filter: str = "",
                       sort: str = "desc") -> dict:
    """Paginated history. Returns items + total count for the filter."""
    pool = await connect()
    async with pool.acquire() as conn:
        where: list[str] = []
        params: list[str | int] = []
        if search:
            where.append(
                "(code ILIKE $%d OR captain0 ILIKE $%d OR captain1 ILIKE $%d OR lobby_name ILIKE $%d)"
                % (len(params) + 1, len(params) + 2, len(params) + 3, len(params) + 4)
            )
            pat = f"%{search}%"
            params += [pat, pat, pat, pat]
        if status_filter:
            where.append(f"status = ${len(params) + 1}")
            params.append(status_filter)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        order = "ASC" if sort == "asc" else "DESC"
        total = await conn.fetchval(
            f"SELECT count(*) FROM lobbies{where_sql}", *params
        )
        rows = await conn.fetch(
            f"SELECT * FROM lobbies{where_sql} ORDER BY created_at {order}, code LIMIT $%d OFFSET $%d"
            % (len(params) + 1, len(params) + 2),
            *params, limit, offset,
        )
        return {"items": [dict(r) for r in rows], "total": total}


async def get_history_detail(code: str) -> dict | None:
    pool = await connect()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM lobbies WHERE code=$1", code)
        if not row:
            return None
        moves = await conn.fetch(
            "SELECT step, team, phase, hero_id, hero_name, source, created_at"
            " FROM draft_moves WHERE code=$1 ORDER BY step", code
        )
        return {**dict(row), "moves": [dict(m) for m in moves]}


async def cleanup_stale_waiting(min_age_minutes: int = 10,
                                min_captains: int = 2) -> list[str]:
    """Delete lobbies stuck in 'waiting' with fewer than 2 captains and
    older than min_age. Returns the codes that were deleted."""
    pool = await connect()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT code FROM lobbies
               WHERE status = 'waiting'
                 AND captain1 IS NULL
                 AND created_at < now() - make_interval(mins => $1)
               LIMIT 100""",
            min_age_minutes,
        )
        codes = [r["code"] for r in rows]
        if codes:
            await conn.execute(
                "DELETE FROM lobbies WHERE code = ANY($1::text[])", codes
            )
        return codes


async def delete_lobby(code: str) -> None:
    """Hard-delete a lobby row (used when evicting an in-memory lobby)."""
    try:
        pool = await connect()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM lobbies WHERE code=$1", code)
    except Exception:
        pass
