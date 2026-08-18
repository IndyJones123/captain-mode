import type { Hero, RoomState } from './types'

const BASE = ''

async function j<T>(p: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${p}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<T>
}

export const api = {
  heroes: () => j<Hero[]>('/api/heroes'),

  createLobby: (name: string, color: number, lobbyName?: string, turnMs?: number, reserveMs?: number) =>
    j<{ code: string; seat_id: number; team: number; color: number; turn_ms?: number; reserve_ms?: number }>('/api/lobby/create', {
      method: 'POST',
      body: JSON.stringify({
        name, color, lobby_name: lobbyName ?? '',
        turn_ms: turnMs ?? 10000, reserve_ms: reserveMs ?? 60000,
      }),
    }),

  joinLobby: (code: string, name: string, seatId?: number) =>
    j<{ code: string; seat_id: number; team: number | null; color: number; rejoined?: boolean }>(
      `/api/lobby/join?code=${encodeURIComponent(code)}`,
      { method: 'POST', body: JSON.stringify({ name, seat_id: seatId ?? null }) },
    ),

  startDraft: (code: string) =>
    j<{ ok?: boolean; error?: string }>(`/api/lobby/start?code=${encodeURIComponent(code)}`, {
      method: 'POST',
    }),

  coinFlip: (code: string) =>
    j<{ ok?: boolean; error?: string; winner_seat?: number; winner_name?: string; winner_team?: number }>(
      `/api/lobby/coin-flip?code=${encodeURIComponent(code)}`,
      { method: 'POST' },
    ),

  chooseSide: (code: string, seatId: number, pick: string) =>
    j<{ ok?: boolean; error?: string }>(
      `/api/lobby/choose-side?code=${encodeURIComponent(code)}&seat_id=${seatId}`,
      { method: 'POST', body: JSON.stringify({ pick }) },
    ),

  getState: (code: string) => j<RoomState>(`/api/lobby/state?code=${encodeURIComponent(code)}`),

  sendAction: (code: string, seatId: number, action: string, heroId: number) =>
    j<{ ok?: boolean; error?: string }>(
      `/api/lobby/action?code=${encodeURIComponent(code)}&seat_id=${seatId}`,
      { method: 'POST', body: JSON.stringify({ action, hero_id: heroId }) },
    ),

  history: (q: { limit?: number; offset?: number; search?: string; status?: string; sort?: string } = {}) =>
    j<{ items: any[]; total: number }>(
      `/api/history?limit=${q.limit ?? 10}&offset=${q.offset ?? 0}&search=${encodeURIComponent(q.search ?? '')}&status=${encodeURIComponent(q.status ?? '')}&sort=${q.sort ?? 'desc'}`,
    ),

  historyDetail: (code: string) =>
    j<any>(`/api/history/${encodeURIComponent(code)}`),
}

export function wsUrl(code: string, seatId: number): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/${code}/${seatId}`
}
