-- 001_init.sql — captain-mode persistence schema (PostgreSQL dialect)
-- Lobbies survive backend restart. Draft moves are append-only.

CREATE TABLE IF NOT EXISTS lobbies (
    code        TEXT PRIMARY KEY,
    host_name   TEXT NOT NULL,
    host_color  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'waiting',
    captain0    TEXT,
    captain1    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS draft_moves (
    id         BIGSERIAL PRIMARY KEY,
    code       TEXT NOT NULL REFERENCES lobbies(code) ON DELETE CASCADE,
    step       INTEGER NOT NULL,
    team       INTEGER NOT NULL,
    phase      TEXT NOT NULL,
    hero_id    INTEGER NOT NULL,
    hero_name  TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_draft_moves_code ON draft_moves(code, step);
