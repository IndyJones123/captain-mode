# Captain Mode — Dota 2 Draft Simulator

Simulasi Captain's Mode draft Dota 2 secara **online realtime** untuk 2 pihak (captain) + spectator, **tanpa login** — cukup share kode lobby 6 karakter.

## Fitur

- **2 captain + spectator bebas** — 2 orang pertama yang join jadi captain (Radiant & Dire), sisanya spectator
- **Tanpa login** — bikin lobby / join cukup pakai nama + kode lobby
- **Realtime** — WebSocket, semua perubahan draft terlihat live oleh semua peserta
- **Aturan Captain's Mode terbaru** (7.36+):
  - First-pick (Radiant): 3 ban → 1 pick → 2 ban → 3 pick → 2 ban → 1 pick
  - Second-pick (Dire): 4 ban → 1 pick → 1 ban → 3 pick → 2 ban → 1 pick
  - Total per tim: 7 ban + 5 pick (24 aksi)
- **Timer per turn 30 detik** — habis waktu auto-pick/ban random
- **127 hero Captain's Mode** — portrait asli dari Steam CDN, filter atribut (Str/Agi/Int), cari nama
- **Riwayat lobby + draft** — tersimpan di database PostgreSQL lokal, bertahan walau server restart; lihat riwayat + detail tiap ban/pick dari halaman home
- **Dark theme** ala Dota, layout papan draft (grid hero tengah, panel tim kiri/kanan)

## Stack

| Layer | Teknologi |
|---|---|
| Backend | Python 3.11 + FastAPI + WebSocket |
| Frontend | Vue 3 + TypeScript + Vite + vue-router + Pinia |
| Database | PostgreSQL 17 lokal (`localhost:5432`, db `captain_mode`, user `captain`), migration SQL di `backend/migrations/` |

## Struktur

```
backend/
  app/
    main.py        # FastAPI app: REST + WS endpoint
    draft.py       # state machine draft (urutan 24 turn)
    lobby.py       # Lobby + LobbyManager (koneksi WS, timer)
    heroes.py      # load hero data
    db.py          # koneksi asyncpg (PostgreSQL) + runner migration + persist + query history
    data/heroes.json  # 127 hero cm_enabled (dari OpenDota constants)
  migrations/
    001_init.sql   # schema: lobbies + draft_moves
frontend/
  src/
    api.ts                 # REST client + wsUrl
    types.ts               # tipe Hero/DraftState
    stores/room.ts         # Pinia store (session, room state)
    composables/useRoomSocket.ts  # WS + reconnect (backoff, stopped flag)
    views/HomeView.vue     # buat/gabung lobby + riwayat lobby
    views/RoomView.vue     # papan draft
```

## Menjalankan

### Backend (port 9002)

```bash
cd backend
uv venv .venv --python 3.11          # sekali saja
uv pip install --python .venv/Scripts/python.exe fastapi "uvicorn[standard]" websockets asyncpg
.venv/Scripts/python.exe -m uvicorn app.main:app --port 9002 --app-dir backend --reload
```

Butuh PostgreSQL 17 lokal: database `captain_mode`, user `captain` (password `captain`).
Migration jalan otomatis saat startup (buat tabel kalau belum ada).

> Sesuaikan kredensial lewat env `CM_PG_DSN` kalau beda, misal:
> `CM_PG_DSN=postgresql://user:pass@host:5432/dbname`

### Frontend (port 5199)

```bash
cd frontend
npm install
npm run dev -- --port 5199
```

Buka `http://localhost:5199`. Vite proxy `/api` + `/ws` → BE 9002.

> Catatan: port 5173 & 5174 dipakai project lain di mesin ini — gunakan 5199.

## API

### REST
- `GET /api/heroes` — daftar hero
- `POST /api/lobby/create` `{name, color}` → `{code, seat_id, team}`
- `POST /api/lobby/join?code=XXX` `{name}` → `{code, seat_id, team}`
- `GET /api/lobby/state?code=XXX` — snapshot room
- `POST /api/lobby/start?code=XXX` — mulai draft (captain)
- `POST /api/lobby/action?code=XXX&seat_id=N` `{action, hero_id}` — ban/pick
- `GET /api/history` — riwayat lobby (terbaru dulu, default 20)
- `GET /api/history/{code}` — detail lobby + daftar move ban/pick

### WebSocket
- `WS /ws/{code}/{seat_id}` — koneksi room
- Incoming: `{"type":"action","action":"ban"|"pick","hero_id":N}`
- Outgoing: `{"type":"state","state":{...}}` (room state lengkap), `{"type":"auto",...}`, `{"type":"error","error":"..."}`

## Alur Draft

1. Captain 1 (host) bikin lobby → dapat kode 6 karakter, share ke teman
2. Teman join → otomatis jadi captain 2 (kalau slot captain masih kosong), atau spectator
3. Captain mana pun bisa tekan **Mulai Draft**
4. Draft jalan turn-by-turn (24 aksi), timer 30 detik per turn
5. Selesai → masing-masing tim punya 7 ban + 5 pick

## Database & Migration

- **PostgreSQL 17** lokal: `localhost:5432`, db `captain_mode`, user `captain` / password `captain`
- Migration: file `.sql` (dialek PostgreSQL) di `backend/migrations/`, dijalankan urut nama saat startup, tercatat di tabel `schema_migrations`
- Tambah kolom/tabel baru → buat `002_xxx.sql`, tinggal restart server
- Bypass DB untuk test: env `CM_PG_DSN` bisa override koneksi (mis. ke database test)

## Catatan

- State lobby **in-memory**: restart backend = semua lobby yang lagi berjalan hilang (tapi **riwayat lobby yang sudah tercatat tetap ada** di PostgreSQL)
- Tanpa auth: siapa pun dengan kode lobby bisa join (2 pertama = captain)
- Portrait hero dari `cdn.cloudflare.steamstatic.com` — butuh internet untuk gambar
