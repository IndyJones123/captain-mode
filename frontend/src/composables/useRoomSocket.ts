import { ref, onUnmounted } from 'vue'
import { useRoomStore } from '../stores/room'
import { wsUrl } from '../api'
import type { WsMessage } from '../types'

export function useRoomSocket(code: string) {
  const store = useRoomStore()
  const isOpen = ref(false)
  const error = ref('')
  const retries = ref(0)
  let ws: WebSocket | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false

  function connect() {
    if (stopped) return
    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return

    ws = new WebSocket(wsUrl(code, store.seatId))
    ws.onopen = () => {
      isOpen.value = true
      retries.value = 0
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WsMessage
        if (msg.type === 'state' && msg.state) {
          store.setRoom(msg.state)
          error.value = ''
        } else if (msg.type === 'error') {
          error.value = msg.error || ''
        }
      } catch { /* ignore */ }
    }
    ws.onclose = () => {
      isOpen.value = false
      ws = null
      scheduleReconnect()
    }
    ws.onerror = () => ws?.close()
  }

  function scheduleReconnect() {
    if (stopped) return
    if (retries.value >= 10) return
    const delay = Math.min(1000 * Math.pow(2, retries.value), 30000)
    retries.value++
    timer = setTimeout(connect, delay)
  }

  function disconnect() {
    stopped = true
    if (timer) { clearTimeout(timer); timer = null }
    if (ws) { ws.close(); ws = null }
    isOpen.value = false
  }

  function sendAction(action: string, heroId: number) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'action', action, hero_id: heroId }))
    }
  }

  onUnmounted(disconnect)
  return { isOpen, error, connect, disconnect, sendAction }
}
