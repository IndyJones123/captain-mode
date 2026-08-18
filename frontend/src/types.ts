export interface Hero {
  id: number
  name: string
  slug: string
  attr: 'str' | 'agi' | 'int' | 'all'
  attack_type: 'Melee' | 'Ranged'
  roles: string[]
  img: string
  icon: string
}

export interface HeroCard {
  id: number
  name: string
  attr: string
  img: string
}

export interface Captain {
  seat_id: number
  name: string
  color: number
}

export interface SideSlot {
  seat_id: number
  name: string
  team: number
}

export interface CoinState {
  phase: 'pending' | 'choose' | 'choose2' | 'done'
  winner_seat: number | null
  winner_name: string | null
  winner_team: number | null
  side_pick: 'radiant' | 'dire' | null
  pick_pick: 'fp' | 'sp' | null
  first_pick: number | null
  _winner_axis: 'side' | 'pick' | null
}

export interface TurnBlock {
  phase: 'ban' | 'pick'
  team: number
  count: number
  start: number
  end: number
}

export interface DraftState {
  started: boolean
  finished: boolean
  phase: 'ban' | 'pick' | 'done'
  team: number
  step: number
  total_steps: number
  phase_label: string
  turn_blocks: TurnBlock[]
  turn_sequence: { phase: 'ban' | 'pick'; team: number }[]
  bans: HeroCard[][]
  picks: HeroCard[][]
  deadline: number | null
  turn_ms: number
  reserve_ms: number
  reserve_left: number[]
}

export interface RoomState {
  code: string
  host: string
  lobby_name: string
  captains: (Captain | null)[]
  sides: (SideSlot | null)[]
  coin: CoinState
  can_start: boolean
  spectator_count: number
  draft: DraftState
}

export interface WsMessage {
  type: 'state' | 'auto' | 'coin' | 'error' | 'pong'
  state?: RoomState
  team?: number
  phase?: string
  hero_id?: number
  error?: string
}

export const ATTR_LABEL: Record<string, string> = {
  str: 'Strength',
  agi: 'Agility',
  int: 'Intelligence',
  all: 'Universal',
}

export const ATTR_COLOR: Record<string, string> = {
  str: '#e05252',
  agi: '#4caf50',
  int: '#42a5f5',
  all: '#b39ddb',
}
