import { defineStore } from 'pinia'

export const useRoomStore = defineStore('room', {
  state: () => ({
    name: localStorage.getItem('cm_name') || '',
    color: Number(localStorage.getItem('cm_color') || 0),
    seatId: Number(localStorage.getItem('cm_seat') || 0),
    myTeam: Number(localStorage.getItem('cm_team') ?? -1),
    isCaptain: false,
    room: null as any,
  }),
  actions: {
    setName(v: string) { this.name = v; localStorage.setItem('cm_name', v) },
    setColor(v: number) { this.color = v; localStorage.setItem('cm_color', String(v)) },
    setSession(seatId: number, team: number | null) {
      this.seatId = seatId
      this.myTeam = team ?? -1
      this.isCaptain = team === 0 || team === 1
      localStorage.setItem('cm_seat', String(seatId))
      localStorage.setItem('cm_team', String(team ?? -1))
    },
    setRoom(room: any) {
      this.room = room
      // After the coin flip, the captain's UI column (Radiant=0/Dire=1) is set by
      // sides[], NOT the join order team. Sync myTeam so turn highlight works.
      if (room && room.sides && this.seatId) {
        const idx = room.sides.findIndex((s: any) => s && s.seat_id === this.seatId)
        if (idx >= 0) {
          this.myTeam = idx
          this.isCaptain = true
          localStorage.setItem('cm_team', String(idx))
        }
      }
    },
    clear() {
      this.seatId = 0; this.myTeam = -1; this.isCaptain = false; this.room = null
      localStorage.removeItem('cm_seat'); localStorage.removeItem('cm_team')
    },
  },
})
