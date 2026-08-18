<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useRoomStore } from '../stores/room'
import { useRoomSocket } from '../composables/useRoomSocket'
import { ATTR_COLOR } from '../types'
import type { Hero } from '../types'

const props = defineProps<{ code: string }>()
const router = useRouter()
const store = useRoomStore()

const heroes = ref<Hero[]>([])
const search = ref('')
const attrFilter = ref<'all' | 'str' | 'agi' | 'int' | 'uni'>('all')
const loading = ref(true)
const notice = ref('')

const room = computed(() => store.room)
const draft = computed(() => room.value?.draft)
const coin = computed(() => room.value?.coin)
const canStart = computed(() => !!room.value?.can_start)

const { isOpen, error, connect, disconnect, sendAction } = useRoomSocket(props.code)

const taken = computed(() => {
  const d = draft.value
  if (!d) return new Set<number>()
  return new Set([...d.bans[0], ...d.bans[1], ...d.picks[0], ...d.picks[1]].map((h: any) => h.id))
})

const myTurn = computed(() => {
  const d = draft.value
  return !!d && d.started && !d.finished && store.isCaptain && d.team === store.myTeam
})

const phase = computed(() => draft.value?.phase || 'ban')

const isCoinPending = computed(() => coin.value?.phase === 'pending')
const isCoinChoose = computed(() => coin.value?.phase === 'choose')
const isCoinChoose2 = computed(() => coin.value?.phase === 'choose2')
const isCoinDone = computed(() => coin.value?.phase === 'done')
const isCoinWinner = computed(() => !!coin.value && coin.value.winner_seat === store.seatId)
const isWinnerChoosing = computed(() => isCoinChoose.value && isCoinWinner.value)
const isLoserChoosing = computed(() => isCoinChoose2.value && !isCoinWinner.value)
const pickLabel = (p: string | null | undefined) =>
  p === 'radiant' ? 'RADIANT' : p === 'dire' ? 'DIRE' : p === 'fp' ? 'FIRST PICK' : p === 'sp' ? 'SECOND PICK' : ''

const pickAt = (t: number, i: number) => draft.value?.picks[t]?.[i] ?? null
const banAt = (t: number, i: number) => draft.value?.bans[t]?.[i] ?? null
const turnTeamName = computed(() =>
  draft.value?.team === 0 ? 'RADIANT' : draft.value?.team === 1 ? 'DIRE' : '')

const sideName = (t: number) => (t === 0 ? 'RADIANT' : 'DIRE')

// --- timeline: urutan ban/pick per tim, blok aktif di-highlight ---
const blocks = computed(() => draft.value?.turn_blocks || [])
const currentStep = computed(() => draft.value?.step ?? 0)
const blockState = (b: any) => {
  const s = currentStep.value
  if (draft.value?.finished) return 'done'
  if (s >= b.start && s <= b.end) return 'active'
  if (s > b.end) return 'done'
  return 'todo'
}
const blockLabel = (b: any) =>
  `${b.phase === 'ban' ? 'BAN' : 'PICK'}×${b.count} ${sideName(b.team)}`

// --- vertical timeline: 24 rows (Radiant | step | Dire), like in-game draft ---
const sequence = computed<{ phase: 'ban' | 'pick'; team: number }[]>(
  () => draft.value?.turn_sequence || [])
const timelineRows = computed(() => {
  const cnt: Record<number, { ban: number; pick: number }> = { 0: { ban: 0, pick: 0 }, 1: { ban: 0, pick: 0 } }
  return sequence.value.map((t, step) => {
    const slot = cnt[t.team][t.phase]
    cnt[t.team][t.phase] += 1
    return {
      step: step + 1,
      phase: t.phase,
      team: t.team,
      slot,
      hero: t.phase === 'ban' ? banAt(t.team, slot) : pickAt(t.team, slot),
      active: draft.value?.started && !draft.value?.finished && step === currentStep.value,
      done: draft.value?.finished || step < currentStep.value,
    }
  })
})

// --- timer: countdown driven by a local clock tick so it updates every 250ms ---
const deadline = computed(() => draft.value?.deadline ?? null)
const now = ref(Date.now())
const remaining = computed(() => {
  const dl = deadline.value
  if (dl === null || dl === undefined) return null
  if (draft.value?.finished) return 0
  return Math.max(0, (dl * 1000 - now.value) / 1000)
})
const timerPct = computed(() => {
  const dl = deadline.value
  const ms = draft.value?.turn_ms
  const rl = draft.value?.reserve_left?.[draft.value?.team ?? 0] ?? 0
  if (!dl || !ms) return 0
  const total = ms + rl
  return Math.min(100, Math.max(0, ((dl * 1000 - now.value) / total) * 100))
})
const fmtDur = (ms: number | null | undefined): string => {
  if (ms === null || ms === undefined || ms <= 0) return '0s'
  const s = Math.ceil(ms / 1000)
  if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${s}s`
}

// --- hero grouped by primary attribute ---
const GROUPS: { key: 'str' | 'agi' | 'int' | 'uni'; label: string; css: string }[] = [
  { key: 'str', label: 'STRENGTH', css: 'grp-str' },
  { key: 'agi', label: 'AGILITY', css: 'grp-agi' },
  { key: 'int', label: 'INTELLIGENCE', css: 'grp-int' },
  { key: 'uni', label: 'UNIVERSAL', css: 'grp-uni' },
]
const searchQ = computed(() => search.value.trim().toLowerCase())

function groupHeroes(key: 'str' | 'agi' | 'int' | 'uni') {
  const af = attrFilter.value
  if (af !== 'all' && af !== key) return []
  const q = searchQ.value
  return heroes.value.filter(h => {
    if (af === 'all' && h.attr === 'all' && key !== 'uni') return false
    if (h.attr !== (key === 'uni' ? 'all' : key)) return false
    return !q || h.name.toLowerCase().includes(q)
  })
}
const strHeroes = computed(() => groupHeroes('str'))
const agiHeroes = computed(() => groupHeroes('agi'))
const intHeroes = computed(() => groupHeroes('int'))
const uniHeroes = computed(() => groupHeroes('uni'))
const anyHeroVisible = computed(() =>
  strHeroes.value.length + agiHeroes.value.length + intHeroes.value.length + uniHeroes.value.length > 0)

function onHeroClick(h: Hero) {
  if (!myTurn.value) return
  notice.value = ''
  sendAction(phase.value, h.id)
}

async function startDraft() {
  notice.value = ''
  const r = await api.startDraft(props.code)
  if ((r as any).error) notice.value = (r as any).error
}

async function flipCoin() {
  notice.value = ''
  const r = await api.coinFlip(props.code)
  if ((r as any).error) notice.value = (r as any).error
}

async function chooseSide(pick: 'radiant' | 'dire' | 'fp' | 'sp') {
  notice.value = ''
  const r = await api.chooseSide(props.code, store.seatId, pick)
  if ((r as any).error) notice.value = (r as any).error
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(props.code)
    notice.value = 'Kode lobby disalin!'
  } catch {
    notice.value = 'Gagal menyalin — salin manual: ' + props.code
  }
}

function leave() {
  disconnect()
  store.clear()
  router.push('/')
}

let tick: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  const hs = await api.heroes().catch(() => [] as Hero[])
  heroes.value = hs
  loading.value = false
  connect()
  tick = setInterval(() => { now.value = Date.now() }, 250)
})

onUnmounted(() => {
  if (tick) clearInterval(tick)
  disconnect()
})
</script>

<template>
  <div class="room">
    <header class="topbar">
      <div class="mode">CAPTAIN'S MODE</div>
      <div class="lobby">
        <span v-if="room?.lobby_name" class="lobby-name">{{ room.lobby_name }}</span>
        <span class="code-chip" title="Kode lobby — klik untuk salin" @click="copyCode">{{ props.code }}</span>
        <span class="conn" :class="{ off: !isOpen }">{{ isOpen ? '● LIVE' : '○ CONNECTING…' }}</span>
      </div>
      <div class="me">
        <span class="seat">{{ store.name }} <b>{{ store.isCaptain ? 'CAPTAIN' : 'SPECTATOR' }}</b></span>
        <button class="ghost" @click="leave">KELUAR</button>
      </div>
    </header>

    <main class="board">
      <!-- ARENA / hero grid — kiri (2/3) -->
      <section class="arena">
        <div class="arena-top">
          <div class="turn-banner">
            <template v-if="draft?.finished">DRAFT SELESAI — PICK SELESAI</template>
            <template v-else-if="draft?.started">{{ phase === 'pick' ? 'PICK PHASE' : 'BAN PHASE' }} — {{ turnTeamName }}</template>
            <template v-else>MENUNGGU PEMILIH</template>
          </div>
          <div class="big-timer" :class="{ urgent: (remaining ?? 99) <= 10 && !draft?.finished }">
            <span class="num">{{ remaining === null ? '—' : Math.ceil(remaining) }}</span>
            <div class="timer-bar" v-if="remaining !== null">
              <div class="timer-fill" :style="{ width: timerPct + '%' }"></div>
            </div>
          </div>
        </div>

        <!-- TIMELINE urutan ban/pick -->
        <div class="timeline" v-if="draft?.started || blocks.length">
          <div
            v-for="(b, i) in blocks"
            :key="i"
            class="tl-block"
            :class="[blockState(b), b.team === 0 ? 'rad' : 'dir']"
            :title="blockLabel(b)"
          >
            {{ blockLabel(b) }}
          </div>
        </div>

        <div class="controls">
          <input v-model="search" placeholder="Cari hero…" class="search" />
          <div class="filters">
            <button :class="['f', { on: attrFilter === 'all' }]" @click="attrFilter = 'all'">SEMUA</button>
            <button :class="['f', { on: attrFilter === 'str' }]" style="color: var(--accent)" @click="attrFilter = 'str'">STR</button>
            <button :class="['f', { on: attrFilter === 'agi' }]" style="color: var(--accent-2)" @click="attrFilter = 'agi'">AGI</button>
            <button :class="['f', { on: attrFilter === 'int' }]" style="color: var(--blue)" @click="attrFilter = 'int'">INT</button>
            <button :class="['f', { on: attrFilter === 'uni' }]" style="color: #b39ddb" @click="attrFilter = 'uni'">UNI</button>
          </div>
        </div>

        <div class="hero-groups">
          <template v-for="g in GROUPS" :key="g.key">
            <div v-if="groupHeroes(g.key).length" class="hero-group">
              <div class="group-head" :class="g.css">
                <span class="group-label">{{ g.label }}</span>
                <span class="group-count">{{ groupHeroes(g.key).length }}</span>
              </div>
              <div class="hero-grid">
                <button
                  v-for="h in groupHeroes(g.key)"
                  :key="h.id"
                  class="hero"
                  :class="{ off: taken.has(h.id), mine: myTurn && !taken.has(h.id) }"
                  :disabled="!myTurn || taken.has(h.id)"
                  @click="onHeroClick(h)"
                >
                  <img :src="h.img" :alt="h.name" loading="lazy" />
                  <span class="h-name">{{ h.name }}</span>
                  <span class="h-attr" :style="{ background: ATTR_COLOR[h.attr] }"></span>
                </button>
              </div>
            </div>
          </template>
          <p v-if="!anyHeroVisible" class="no-match">Tidak ada hero yang cocok dengan pencarian.</p>
        </div>

        <div class="start-zone">
          <!-- COIN FLIP -->
          <template v-if="!draft?.started && isCoinPending">
            <div class="coin-box">
              <div class="coin-title">COIN FLIP</div>
              <p class="waiting">2 captain sudah masuk — lempar koin untuk menentukan siapa yang memilih sisi terlebih dahulu</p>
              <button class="btn-start" :disabled="!store.isCaptain" @click="flipCoin">LEMPAR KOIN</button>
            </div>
          </template>
          <template v-else-if="!draft?.started && isCoinChoose">
            <div class="coin-box">
              <div class="coin-title">COIN FLIP — PILIHAN PEMENANG</div>
              <p class="waiting">🏆 {{ coin?.winner_name }} MENANG! Pilih satu: sisi (RADIANT/DIRE) atau urutan pick (FIRST/SECOND PICK). Yang kalah akan memilih dari opsi lainnya.</p>
              <div v-if="isWinnerChoosing" class="coin-choices">
                <button class="btn-side radiant-btn" @click="chooseSide('radiant')">RADIANT</button>
                <button class="btn-side dire-btn" @click="chooseSide('dire')">DIRE</button>
                <button class="btn-side fp-btn" @click="chooseSide('fp')">FIRST PICK</button>
                <button class="btn-side sp-btn" @click="chooseSide('sp')">SECOND PICK</button>
              </div>
              <p v-else class="waiting">Menunggu {{ coin?.winner_name }} memilih…</p>
            </div>
          </template>
          <template v-else-if="!draft?.started && isCoinChoose2">
            <div class="coin-box">
              <div class="coin-title">COIN FLIP — PILIHAN LAWAN</div>
              <p class="waiting">
                🏆 {{ coin?.winner_name }} memilih <b>{{ pickLabel(coin?._winner_axis === 'side' ? coin?.side_pick : coin?.pick_pick) }}</b>.
                {{ isLoserChoosing ? 'Sekarang giliranmu memilih dari opsi yang tersisa:' : 'Menunggu lawan memilih…' }}
              </p>
              <div v-if="isLoserChoosing" class="coin-choices">
                <template v-if="coin?.side_pick">
                  <!-- winner picked side -> loser picks pick order -->
                  <button class="btn-side fp-btn" @click="chooseSide('fp')">FIRST PICK</button>
                  <button class="btn-side sp-btn" @click="chooseSide('sp')">SECOND PICK</button>
                </template>
                <template v-else>
                  <!-- winner picked pick order -> loser picks side -->
                  <button class="btn-side radiant-btn" @click="chooseSide('radiant')">RADIANT</button>
                  <button class="btn-side dire-btn" @click="chooseSide('dire')">DIRE</button>
                </template>
              </div>
              <p v-else class="waiting">Menunggu lawan memilih…</p>
            </div>
          </template>
          <template v-else-if="!draft?.started && isCoinDone">
            <div class="coin-box">
              <div class="coin-title">COIN FLIP SELESAI</div>
              <p class="waiting">
                🏆 {{ coin?.winner_name }} memilih <b>{{ pickLabel(coin?._winner_axis === 'side' ? coin?.side_pick : coin?.pick_pick) }}</b>,
                lawan memilih <b>{{ pickLabel(coin?._winner_axis === 'side' ? coin?.pick_pick : coin?.side_pick) }}</b>.
              </p>
              <p class="waiting side-summary">
                {{ coin?.first_pick === store.seatId ? 'Kamu' : 'Lawan' }} FIRST PICK
                <span class="vs">·</span>
                {{ coin?.first_pick === store.seatId ? 'Lawan' : 'Kamu' }} SECOND PICK
              </p>
              <p v-if="store.isCaptain" class="start-row">
                <button class="btn-start" :disabled="!canStart" @click="startDraft">MULAI DRAFT</button>
              </p>
            </div>
          </template>

          <p v-if="!draft?.started && !store.isCaptain && !isCoinDone" class="waiting">Menunggu captain memulai draft…</p>
        </div>
        <p v-if="notice" class="notice">{{ notice }}</p>
        <p v-if="error" class="err">{{ error }}</p>
      </section>

      <!-- DRAFT TIMELINE — vertical 24 rows: Radiant | step | Dire -->
      <section class="side-panel">
        <div class="tl-head">
          <div class="tl-side radiant">RADIANT</div>
          <div class="tl-mid">URUTAN</div>
          <div class="tl-side dire">DIRE</div>
        </div>
        <div class="tl-reserve">
          <span class="rsv rad" :class="{ low: (draft?.reserve_left?.[0] ?? 0) < 10000 }">
            ⏱ {{ fmtDur(draft?.reserve_left?.[0]) }}
          </span>
          <span class="rsv-label">RESERVE</span>
          <span class="rsv dir" :class="{ low: (draft?.reserve_left?.[1] ?? 0) < 10000 }">
            {{ fmtDur(draft?.reserve_left?.[1]) }} ⏱
          </span>
        </div>
        <div class="draft-timeline">
          <div
            v-for="row in timelineRows"
            :key="row.step"
            class="tl-row"
            :class="{
              active: row.active,
              done: row.done,
              ban: row.phase === 'ban',
              pick: row.phase === 'pick',
              'side-0': row.team === 0,
              'side-1': row.team === 1,
            }"
          >
            <!-- Radiant cell -->
            <div class="tl-cell rad" :class="{ fill: row.team === 0 && row.hero, empty: row.team === 1 }">
              <template v-if="row.team === 0">
                <template v-if="row.hero">
                  <img :src="row.hero.img" :alt="row.hero.name" />
                  <span class="tl-hero-name">{{ row.hero.name }}</span>
                  <span v-if="row.phase === 'ban'" class="tl-ban-x">✕</span>
                </template>
                <span v-else class="tl-empty-label">{{ row.phase === 'ban' ? 'BAN' : 'PICK' }}</span>
              </template>
            </div>
            <!-- Center step -->
            <div class="tl-step" :class="row.phase">
              <span class="tl-num">{{ row.step }}</span>
              <span class="tl-phase">{{ row.phase.toUpperCase() }}</span>
            </div>
            <!-- Dire cell -->
            <div class="tl-cell dir" :class="{ fill: row.team === 1 && row.hero, empty: row.team === 0 }">
              <template v-if="row.team === 1">
                <template v-if="row.hero">
                  <img :src="row.hero.img" :alt="row.hero.name" />
                  <span class="tl-hero-name">{{ row.hero.name }}</span>
                  <span v-if="row.phase === 'ban'" class="tl-ban-x">✕</span>
                </template>
                <span v-else class="tl-empty-label">{{ row.phase === 'ban' ? 'BAN' : 'PICK' }}</span>
              </template>
            </div>
          </div>
        </div>
      </section>
    </main>

    <footer class="statusbar">
      <span v-if="loading">MEMUAT HERO…</span>
      <span v-else>{{ heroes.length }} HERO · {{ room?.spectator_count ?? 0 }} SPECTATOR</span>
      <span v-if="draft?.started && !draft.finished">TURN {{ (draft?.step || 0) + 1 }}/{{ draft?.total_steps }}</span>
    </footer>
  </div>
</template>

<style scoped>
.room { min-height: 100%; display: flex; flex-direction: column; }

/* ---------- top bar ---------- */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 22px; height: 52px;
  background: rgba(8, 12, 16, .92);
  border-bottom: 1px solid rgba(255, 255, 255, .07);
}
.mode { font-weight: 800; letter-spacing: 4px; font-size: 15px; color: #d9b13d; text-shadow: 0 0 18px rgba(217, 177, 61, .35); }
.lobby { display: flex; align-items: center; gap: 12px; }
.lobby-name { font-size: 13px; font-weight: 700; color: #cfd8e3; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.code-chip { font-family: 'Segoe UI', monospace; font-weight: 700; letter-spacing: 3px; font-size: 15px;
  color: #cfd8e3; background: rgba(255, 255, 255, .05); border: 1px solid rgba(255, 255, 255, .12);
  padding: 4px 14px; border-radius: 6px; cursor: pointer; }
.conn { font-size: 11px; letter-spacing: 1px; color: #6fce7f; }
.conn.off { color: #7a8794; }
.me { display: flex; align-items: center; gap: 14px; }
.seat { font-size: 12px; color: #9aa7b4; letter-spacing: .5px; }
.seat b { color: #e8eef4; }
.ghost { background: transparent; border: 1px solid rgba(255, 255, 255, .18); padding: 6px 14px; font-size: 11px;
  letter-spacing: 1.5px; color: #cfd8e3; border-radius: 6px; }

/* ---------- board: hero grid kiri (2/3) + panel tim kanan (1/3) ---------- */
.board { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 16px;
  flex: 1; padding: 16px 22px; min-height: 0; }

/* ---------- arena / hero grid ---------- */
.arena { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.arena-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.turn-banner { font-size: 15px; font-weight: 800; letter-spacing: 3px; color: #dfe6ee; }
.big-timer { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.big-timer .num { font-family: 'Segoe UI', monospace; font-size: 38px; font-weight: 800; line-height: 1; color: #d9b13d;
  text-shadow: 0 0 22px rgba(217, 177, 61, .45); min-width: 64px; text-align: right; }
.big-timer.urgent .num { color: #ff5c5c; text-shadow: 0 0 22px rgba(255, 92, 92, .55); animation: pulse 1s infinite; }
@keyframes pulse { 50% { opacity: .45; } }
.timer-bar { width: 130px; height: 4px; border-radius: 2px; background: rgba(255, 255, 255, .1); overflow: hidden; }
.timer-fill { height: 100%; background: linear-gradient(90deg, #d9b13d, #ffd875); transition: width .25s linear; }
.big-timer.urgent .timer-fill { background: linear-gradient(90deg, #cf3f3f, #ff5c5c); }

/* ---------- timeline urutan ban/pick ---------- */
.timeline { display: flex; flex-wrap: wrap; gap: 5px; }
.tl-block { font-size: 10px; font-weight: 800; letter-spacing: .5px; padding: 4px 8px; border-radius: 5px;
  background: rgba(255, 255, 255, .04); border: 1px solid rgba(255, 255, 255, .09); color: #7a8794; }
.tl-block.rad { color: #6fce7f; }
.tl-block.dir { color: #ef6a6a; }
.tl-block.todo { opacity: .45; }
.tl-block.active { background: rgba(217, 177, 61, .16); border-color: #d9b13d; color: #f0d98a;
  box-shadow: 0 0 10px rgba(217, 177, 61, .3); }
.tl-block.done { background: rgba(255, 255, 255, .06); opacity: 1; }

/* ---------- controls ---------- */
.controls { display: flex; gap: 10px; align-items: center; }
.search { flex: 1; background: rgba(0, 0, 0, .4); border: 1px solid rgba(255, 255, 255, .12); border-radius: 6px; padding: 8px 12px; font-size: 13px; }
.filters { display: flex; gap: 6px; }
.f { padding: 7px 12px; font-size: 11px; letter-spacing: 1px; background: rgba(0, 0, 0, .35); border: 1px solid rgba(255, 255, 255, .1);
  border-radius: 6px; color: #9aa7b4; font-weight: 700; }
.f.on { background: rgba(217, 177, 61, .18); border-color: #d9b13d; color: #f0d98a; }

.hero-groups { overflow-y: auto; flex: 1; padding: 2px; display: flex; flex-direction: column; gap: 14px; }
.hero-group { display: flex; flex-direction: column; gap: 7px; }
.group-head { display: flex; align-items: center; justify-content: space-between; padding: 5px 10px;
  border-radius: 6px; font-weight: 800; letter-spacing: 2px; font-size: 12px; color: #e8eef4;
  border: 1px solid rgba(255, 255, 255, .12); background: rgba(255, 255, 255, .04); }
.group-count { font-size: 11px; font-weight: 700; color: #9aa7b4; letter-spacing: 1px; }
.grp-str { border-left: 4px solid #e05252; }
.grp-agi { border-left: 4px solid #4caf50; }
.grp-int { border-left: 4px solid #42a5f5; }
.grp-uni { border-left: 4px solid #b39ddb; }
.no-match { text-align: center; color: #7a8794; font-size: 13px; padding: 30px 0; }

.hero-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(86px, 1fr)); gap: 7px; }
.hero { position: relative; padding: 0; border-radius: 6px; overflow: hidden;
  background: rgba(0, 0, 0, .4); border: 1.5px solid rgba(255, 255, 255, .1); display: flex; flex-direction: column; transition: transform .12s; }
.hero:hover:not(:disabled) { transform: scale(1.05); z-index: 2; filter: brightness(1.18); }
.hero img { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }
.h-name { font-size: 10px; font-weight: 600; padding: 3px 5px; text-align: left; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; color: #cfd8e3; letter-spacing: .3px; }
.h-attr { position: absolute; top: 4px; left: 4px; width: 9px; height: 9px; border-radius: 50%; border: 1.5px solid rgba(0, 0, 0, .7); }
.hero.off { opacity: .3; filter: grayscale(.8); }
.hero.mine:not(:disabled) { border-color: #d9b13d; box-shadow: 0 0 14px rgba(217, 177, 61, .35); }

.start-zone { min-height: 30px; }
.start-row { display: flex; justify-content: center; }
.btn-start { background: linear-gradient(180deg, #f0cf6a, #c9972f); color: #231a06; font-weight: 800; letter-spacing: 2px;
  padding: 12px 34px; border-radius: 7px; font-size: 14px; box-shadow: 0 4px 18px rgba(217, 177, 61, .35); }
.btn-start:disabled { opacity: .4; box-shadow: none; }
.coin-box { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 14px;
  border: 1px solid rgba(217, 177, 61, .35); border-radius: 10px; background: rgba(217, 177, 61, .06); }
.coin-title { font-weight: 800; letter-spacing: 3px; font-size: 14px; color: #d9b13d; }
.coin-choices { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.side-summary { margin-top: 2px; color: #9aa7b4; font-size: 13px; }
.side-summary .vs { color: #5c6b78; margin: 0 6px; }
.btn-side { padding: 10px 16px; font-weight: 800; letter-spacing: 1px; font-size: 12px; border-radius: 7px;
  color: #0e141a; cursor: pointer; border: none; transition: transform .1s; }
.btn-side:hover { transform: scale(1.05); }
.radiant-btn { background: linear-gradient(180deg, #7cd98a, #2f8a44); box-shadow: 0 2px 10px rgba(86, 196, 110, .35); }
.dire-btn { background: linear-gradient(180deg, #ef7d7d, #a82828); box-shadow: 0 2px 10px rgba(224, 74, 74, .35); }
.fp-btn { background: linear-gradient(180deg, #f0cf6a, #c9972f); box-shadow: 0 2px 10px rgba(217, 177, 61, .35); }
.sp-btn { background: linear-gradient(180deg, #9aa7b4, #5a6572); box-shadow: 0 2px 10px rgba(154, 167, 180, .35); }
.waiting { text-align: center; color: #9aa7b4; font-size: 12px; letter-spacing: .5px; }
.notice { color: #6fce7f; font-size: 12px; text-align: center; letter-spacing: .5px; }
.err { color: #ff5c5c; font-size: 12px; text-align: center; }

/* ---------- draft timeline kanan: Radiant | step | Dire (24 rows) ---------- */
.side-panel { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.tl-head { display: grid; grid-template-columns: 1fr 56px 1fr; gap: 4px; align-items: center; padding: 0 2px; }
.tl-side { font-size: 11px; font-weight: 800; letter-spacing: 2px; padding: 4px 8px; border-radius: 5px; text-align: center; }
.tl-side.radiant { color: #6fce7f; background: rgba(86, 196, 110, .12); border: 1px solid rgba(86, 196, 110, .35); }
.tl-side.dire { color: #ef6a6a; background: rgba(224, 74, 74, .12); border: 1px solid rgba(224, 74, 74, .35); }
.tl-mid { font-size: 9px; font-weight: 700; letter-spacing: 1px; color: #7a8794; text-align: center; }

.tl-reserve { display: grid; grid-template-columns: 1fr auto 1fr; gap: 4px; align-items: center; padding: 0 2px; }
.rsv { font-size: 11px; font-weight: 700; font-family: 'Segoe UI', monospace; padding: 2px 6px; border-radius: 4px; text-align: center; }
.rsv.rad { color: #6fce7f; background: rgba(86, 196, 110, .08); }
.rsv.dir { color: #ef6a6a; background: rgba(224, 74, 74, .08); }
.rsv.low { color: #ffd54f; background: rgba(255, 179, 0, .1); }
.rsv-label { font-size: 8px; letter-spacing: 2px; color: #7a8794; font-weight: 700; }

.draft-timeline { overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 3px; padding: 2px; }
.tl-row { display: grid; grid-template-columns: 1fr 56px 1fr; gap: 4px; align-items: stretch; }
.tl-cell { position: relative; height: 40px; border-radius: 5px; overflow: hidden;
  background: rgba(0, 0, 0, .32); border: 1px dashed rgba(255, 255, 255, .12);
  display: flex; align-items: center; justify-content: center; }
.tl-cell.empty { background: rgba(0, 0, 0, .12); border-style: dashed; }
.tl-cell.fill { border-style: solid; border-color: rgba(255, 255, 255, .16); }
.tl-cell img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
/* banned hero: grayscale + red X overlay; picked hero keeps full color */
.tl-cell img { filter: none; }
.tl-row.ban .tl-cell img { filter: grayscale(1) brightness(.6); }
.tl-cell .tl-ban-x { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 26px; font-weight: 900; color: #ff4d4d; text-shadow: 0 0 8px rgba(255, 0, 0, .8), 0 1px 2px rgba(0, 0, 0, .9);
  background: rgba(0, 0, 0, .25); z-index: 2; }
.tl-hero-name { position: absolute; bottom: 0; left: 0; right: 0; padding: 2px 5px;
  font-size: 9px; font-weight: 700; letter-spacing: .3px; color: #eef3f8;
  background: linear-gradient(180deg, transparent, rgba(0, 0, 0, .85)); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tl-empty-label { font-size: 9px; font-weight: 700; letter-spacing: 1.5px; color: rgba(255, 255, 255, .28); }

.tl-step { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0;
  border-radius: 5px; background: rgba(255, 255, 255, .04); border: 1px solid rgba(255, 255, 255, .08); }
.tl-num { font-size: 13px; font-weight: 800; color: #9aa7b4; line-height: 1.1; }
.tl-phase { font-size: 8px; font-weight: 800; letter-spacing: 1px; color: #7a8794; }
/* phase label warna IKUT TIM (Radiant hijau / Dire merah), bukan ikut ban/pick */
.tl-row.side-0 .tl-phase { color: #6fce7f; }
.tl-row.side-1 .tl-phase { color: #ef6a6a; }
.tl-row.side-0 .tl-num { color: #9fd9a8; }
.tl-row.side-1 .tl-num { color: #e8a0a0; }

/* done rows dim */
.tl-row.done .tl-cell { opacity: .85; }
.tl-row.done .tl-num { color: #5b6672; }

/* active row: glow + highlight the acting side */
.tl-row.active { position: relative; }
.tl-row.active .tl-step { background: rgba(217, 177, 61, .2); border-color: #d9b13d; box-shadow: 0 0 12px rgba(217, 177, 61, .4); }
.tl-row.active .tl-num { color: #f0d98a; }
.tl-row.active .tl-phase { color: #f0d98a; }
.tl-row.active.side-0 .tl-cell.rad { border-color: #6fce7f; box-shadow: 0 0 14px rgba(86, 196, 110, .45), inset 0 0 20px rgba(86, 196, 110, .12); }
.tl-row.active.side-1 .tl-cell.dir { border-color: #ef6a6a; box-shadow: 0 0 14px rgba(224, 74, 74, .45), inset 0 0 20px rgba(224, 74, 74, .12); }
.tl-row.active.side-0 .tl-cell.rad::before, .tl-row.active.side-1 .tl-cell.dir::before {
  content: '▶'; position: absolute; left: 4px; top: 50%; transform: translateY(-50%);
  color: #f0d98a; font-size: 12px; z-index: 3; text-shadow: 0 0 6px rgba(217, 177, 61, .9); }
.tl-row.active.side-1 .tl-cell.dir::before { left: auto; right: 4px; }

/* ---------- status bar ---------- */
.statusbar { border-top: 1px solid rgba(255, 255, 255, .07); padding: 7px 22px; display: flex; justify-content: space-between;
  font-size: 11px; letter-spacing: 1px; color: #7a8794; background: rgba(8, 12, 16, .92); }
</style>
