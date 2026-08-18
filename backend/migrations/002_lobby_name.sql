-- 002_lobby_name.sql — add lobby name field to lobbies
ALTER TABLE lobbies ADD COLUMN IF NOT EXISTS lobby_name TEXT NOT NULL DEFAULT '';
