-- 003_timers.sql — per-lobby turn duration + reserve time (ms)
ALTER TABLE lobbies ADD COLUMN IF NOT EXISTS turn_ms  INTEGER NOT NULL DEFAULT 10000;
ALTER TABLE lobbies ADD COLUMN IF NOT EXISTS reserve_ms INTEGER NOT NULL DEFAULT 60000;
