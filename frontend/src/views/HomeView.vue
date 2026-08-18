<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useRoomStore } from '../stores/room'

const router = useRouter()
const store = useRoomStore()

const mode = ref<'create' | 'join'>('create')
const name = ref(store.name)
const lobbyName = ref('')
const code = ref('')
const color = ref(store.color)
const turnSec = ref(10)
const reserveSec = ref(60)
const error = ref('')
const notice = ref('')
const loading = ref(false)

// --- history: pagination + search + status filter + sort ---
const history = ref<any[]>([])
const total = ref(0)
const historyError = ref('')
const expanded = ref<string | null>(null)
const detailCache = ref<Record<string, any>>({})

const PAGE = 10
const page = ref(1)
const search = ref('')
const statusFilter = ref('')
const sort = ref<'asc' | 'desc'>('desc')
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE)))

const COLORS = ['#e05252', '#4caf50', '#42a5f5', '#ffb300', '#b39ddb', '#f48fb1']

const STATUS_LABEL: Record<string, string> = {
  waiting: 'Menunggu',
  running: 'Berlangsung',
  finished: 'Selesai',
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat('id-ID', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(d)
}

async function loadHistory() {
  try {
    const r = await api.history({
      limit: PAGE,
      offset: (page.value - 1) * PAGE,
      search: search.value,
      status: statusFilter.value,
      sort: sort.value,
    })
    history.value = r.items ?? []
    total.value = r.total ?? 0
    historyError.value = ''
  } catch {
    historyError.value = 'Riwayat tidak bisa dimuat'
  }
}

function onSearch() {
  page.value = 1
  loadHistory()
}

watch([statusFilter, sort], () => { page.value = 1; loadHistory() })
watch(page, loadHistory)
onMounted(loadHistory)

async function toggleDetail(item: any) {
  if (expanded.value === item.code) {
    expanded.value = null
    return
  }
  expanded.value = item.code
  if (!detailCache.value[item.code]) {
    try {
      const r = await api.historyDetail(item.code)
      if ((r as any).error) { historyError.value = (r as any).error; return }
      detailCache.value[item.code] = r
    } catch {
      historyError.value = 'Detail gagal dimuat'
    }
  }
}

async function joinCode(item: any) {
  // Join via API so we get a valid seat for THIS lobby (rejoin by name if the
  // captain's seat is still registered but offline). Pushing straight to the
  // room with a stale seatId would attach a ghost socket and render spectator.
  const nm = store.name || item.captain0 || 'Spectator'
  store.setName(nm)
  try {
    const r: any = await api.joinLobby(item.code, nm, store.seatId || undefined)
    if (r.error) { historyError.value = r.error; return }
    store.setSession(r.seat_id, r.team)
    if (r.rejoined) notice.value = 'Kamu kembali ke kursi lamamu di lobby ini'
  } catch {
    historyError.value = 'Gagal join lobby'
  }
  router.push(`/room/${item.code}`)
}

async function submit() {
  if (!name.value.trim()) { error.value = 'Masukkan nama dulu'; return }
  if (mode.value === 'join' && code.value.trim().length !== 6) { error.value = 'Kode lobby 6 karakter'; return }
  const t = Number(turnSec.value)
  const r = Number(reserveSec.value)
  if (mode.value === 'create') {
    if (!Number.isFinite(t) || t < 1 || t > 300) { error.value = 'Waktu per turn 1–300 detik'; return }
    if (!Number.isFinite(r) || r < 0 || r > 3600) { error.value = 'Reserve time 0–3600 detik'; return }
  }
  loading.value = true
  error.value = ''
  try {
    store.setName(name.value.trim())
    store.setColor(color.value)
    if (mode.value === 'create') {
      const res = await api.createLobby(name.value.trim(), color.value, lobbyName.value.trim(),
        Math.round(t * 1000), Math.round(r * 1000))
      store.setSession(res.seat_id, res.team)
      router.push(`/room/${res.code}`)
    } else {
      const r = await api.joinLobby(code.value.trim().toUpperCase(), name.value.trim(), store.seatId || undefined)
      if ((r as any).error) { error.value = (r as any).error; return }
      store.setSession(r.seat_id, r.team)
      if (r.rejoined) notice.value = 'Kamu kembali ke kursi lamamu di lobby ini'
      router.push(`/room/${r.code}`)
    }
  } catch (e) {
    error.value = 'Gagal terhubung ke server'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="home">
    <header class="hero">
      <h1>CAPTAIN MODE</h1>
      <p class="tagline">Simulasi draft Dota 2 — ban &amp; pick bareng teman, live.</p>
    </header>

    <div class="panel">
      <div class="tabs">
        <button :class="['tab', { on: mode === 'create' }]" @click="mode = 'create'">Buat Lobby</button>
        <button :class="['tab', { on: mode === 'join' }]" @click="mode = 'join'">Gabung Lobby</button>
      </div>

      <form @submit.prevent="submit">
        <label class="field">
          <span>Nama Kamu</span>
          <input v-model="name" maxlength="24" placeholder="Captain / Spectator" autocomplete="off" />
        </label>

        <template v-if="mode === 'create'">
          <label class="field">
            <span>Nama Lobby</span>
            <input v-model="lobbyName" maxlength="40" placeholder="cth: Lobby Seru" autocomplete="off" />
          </label>

          <div class="field time-row">
            <label class="time-field">
              <span>Waktu / Turn (detik)</span>
              <input v-model.number="turnSec" type="number" min="1" max="300" step="1" placeholder="10" />
            </label>
            <label class="time-field">
              <span>Reserve Time (detik)</span>
              <input v-model.number="reserveSec" type="number" min="0" max="3600" step="1" placeholder="60" />
            </label>
          </div>

          <label class="field">
            <span>Warna Tim Radiant</span>
            <div class="colors">
              <button
                v-for="c in COLORS"
                :key="c"
                type="button"
                class="swatch"
                :style="{ background: c }"
                :class="{ on: color === parseInt(c.slice(1), 16) }"
                @click="color = parseInt(c.slice(1), 16)"
              />
            </div>
          </label>
        </template>

        <template v-else>
          <label class="field">
            <span>Kode Lobby</span>
            <input
              v-model="code"
              maxlength="6"
              placeholder="CONTOH: AB12CD"
              class="code-input"
              autocomplete="off"
              @input="code = code.toUpperCase().replace(/[^A-Z0-9]/g, '')"
            />
          </label>
        </template>

        <p v-if="notice" class="ok">{{ notice }}</p>
        <p v-if="error" class="err">{{ error }}</p>

        <button class="btn-primary submit" type="submit" :disabled="loading">
          {{ loading ? '...' : (mode === 'create' ? 'Buat & Masuk' : 'Gabung') }}
        </button>
      </form>
    </div>

    <p class="hint">Tanpa login. 2 captain + spectator bebas. Cukup share kode lobby 6 karakter.</p>

    <section class="history" v-if="history.length || historyError || total > 0">
      <h2>Riwayat Lobby</h2>

      <!-- toolbar: search + filter + sort -->
      <div class="hist-toolbar">
        <input
          v-model="search"
          class="hist-search"
          placeholder="Cari kode / nama / captain…"
          @keyup.enter="onSearch"
        />
        <button class="btn-ghost" @click="onSearch">Cari</button>
        <select v-model="statusFilter" class="hist-select">
          <option value="">Semua status</option>
          <option value="waiting">Menunggu</option>
          <option value="running">Berlangsung</option>
          <option value="finished">Selesai</option>
        </select>
        <button class="btn-ghost" @click="sort = sort === 'desc' ? 'asc' : 'desc'">
          {{ sort === 'desc' ? '↓ Terbaru' : '↑ Terlama' }}
        </button>
      </div>

      <p v-if="historyError" class="err">{{ historyError }}</p>
      <p v-else-if="!history.length" class="no-match">Tidak ada lobby yang cocok.</p>

      <div v-for="item in history" :key="item.code" class="hist-row" :class="{ open: expanded === item.code }">
        <button class="hist-main" @click="toggleDetail(item)">
          <span class="hist-name">{{ item.lobby_name || item.host_name || '—' }}</span>
          <span class="hist-code">{{ item.code }}</span>
          <span class="hist-caps">
            {{ item.captain0 || '—' }} <em>vs</em> {{ item.captain1 || '—' }}
          </span>
          <span class="hist-status" :class="item.status">{{ STATUS_LABEL[item.status] || item.status }}</span>
          <span class="hist-time">{{ fmtDate(item.created_at) }}</span>
        </button>
        <div v-if="expanded === item.code" class="hist-detail">
          <div v-if="detailCache[item.code]" class="moves">
            <div v-for="m in detailCache[item.code].moves" :key="m.step" class="move">
              <span class="mv-step">{{ m.step }}</span>
              <span class="mv-team" :class="'t' + m.team">{{ m.team === 0 ? 'RADIANT' : 'DIRE' }}</span>
              <span class="mv-phase">{{ m.phase === 'ban' ? 'Ban' : 'Pick' }}</span>
              <span class="mv-hero">{{ m.hero_name }}</span>
              <span class="mv-src">{{ m.source === 'auto' ? '(auto)' : '' }}</span>
            </div>
          </div>
          <div v-else class="moves-loading">Memuat…</div>
          <button class="btn-ghost" @click="joinCode(item)">Masuk Lobby</button>
        </div>
      </div>

      <!-- pagination -->
      <div v-if="totalPages > 1" class="hist-pager">
        <button class="btn-ghost" :disabled="page <= 1" @click="page--">‹</button>
        <span class="pager-info">Hal {{ page }} / {{ totalPages }} · {{ total }} lobby</span>
        <button class="btn-ghost" :disabled="page >= totalPages" @click="page++">›</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home { min-height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px; gap: 20px; }
.hero { text-align: center; }
.hero h1 { font-size: 44px; letter-spacing: 6px; color: var(--accent); font-weight: 800; }
.tagline { color: var(--text-dim); margin-top: 6px; }
.panel { width: 100%; max-width: 420px; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; box-shadow: var(--shadow); }
.tabs { display: flex; gap: 8px; margin-bottom: 18px; }
.tab { flex: 1; background: transparent; border: 1px solid var(--border); color: var(--text-dim); }
.tab.on { background: var(--bg-hover); color: var(--text); border-color: var(--blue); }
.field { display: block; margin-bottom: 16px; }
.time-row { display: flex; gap: 10px; }
.time-field { flex: 1; }
.time-field span { display: block; font-size: 13px; color: var(--text-dim); margin-bottom: 6px; }
.field span { display: block; font-size: 13px; color: var(--text-dim); margin-bottom: 6px; }
.colors { display: flex; gap: 10px; }
.swatch { width: 34px; height: 34px; border-radius: 50%; padding: 0; border: 3px solid transparent; }
.swatch.on { border-color: #fff; }
.code-input { text-transform: uppercase; letter-spacing: 4px; font-weight: 700; text-align: center; font-size: 18px; }
.err { color: var(--danger); font-size: 13px; margin: 4px 0 10px; }
.ok { color: #4ade80; font-size: 13px; margin: 4px 0 10px; }
.submit { width: 100%; margin-top: 6px; }
.hint { color: var(--text-dim); font-size: 13px; text-align: center; max-width: 460px; }

.history { width: 100%; max-width: 640px; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 18px; }
.history h2 { font-size: 14px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 2px; margin-bottom: 10px; }
.hist-toolbar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.hist-search { flex: 1; min-width: 160px; }
.hist-select { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.hist-row { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; overflow: hidden; }
.hist-main { display: flex; align-items: center; gap: 10px; width: 100%; background: transparent; color: var(--text); padding: 10px 12px; cursor: pointer; }
.hist-main:hover { background: var(--bg-hover); }
.hist-name { font-weight: 700; font-size: 13px; color: var(--text); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hist-code { font-family: monospace; font-weight: 700; letter-spacing: 1px; color: var(--blue); }
.hist-caps { flex: 1; text-align: left; font-size: 13px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hist-caps em { color: var(--text-dim); font-style: normal; }
.hist-status { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-transform: uppercase; letter-spacing: 1px; white-space: nowrap; }
.hist-status.waiting { background: rgba(66, 165, 245, 0.15); color: #82b1ff; }
.hist-status.running { background: rgba(255, 179, 0, 0.15); color: #ffd54f; }
.hist-status.finished { background: rgba(76, 175, 80, 0.15); color: #81c784; }
.hist-time { font-size: 11px; color: var(--text-dim); white-space: nowrap; }
.hist-detail { border-top: 1px solid var(--border); padding: 10px 12px; background: rgba(0, 0, 0, 0.2); }
.moves { max-height: 220px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.move { display: flex; gap: 8px; align-items: center; font-size: 13px; }
.mv-step { color: var(--text-dim); width: 22px; text-align: right; font-family: monospace; }
.mv-team { font-size: 10px; font-weight: 700; letter-spacing: 1px; width: 64px; }
.mv-team.t0 { color: #ff8a80; }
.mv-team.t1 { color: #81c784; }
.mv-phase { color: var(--text-dim); width: 34px; }
.mv-hero { color: var(--text); }
.mv-src { color: var(--text-dim); font-size: 11px; }
.moves-loading { color: var(--text-dim); font-size: 13px; padding: 8px 0; }
.btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text); font-size: 12px; padding: 6px 14px; }
.btn-ghost:hover { border-color: var(--blue); color: var(--blue); }
.btn-ghost:disabled { opacity: 0.4; cursor: default; }
.no-match { color: var(--text-dim); font-size: 13px; padding: 8px 0; }
.hist-pager { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 10px; }
.pager-info { font-size: 12px; color: var(--text-dim); }
</style>
