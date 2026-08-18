import { useEffect, useRef, useState } from 'react'
import type { BotState } from './types'

/** Conexión websocket al backend con reconexión automática. */
export function useBotSocket() {
  const [state, setState] = useState<BotState | null>(null)
  const [connected, setConnected] = useState(false)
  const retry = useRef(1000)

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: number | undefined
    let closed = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => {
        setConnected(true)
        retry.current = 1000
      }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'state') setState(msg)
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) {
          timer = window.setTimeout(connect, retry.current)
          retry.current = Math.min(retry.current * 2, 15000)
        }
      }
      ws.onerror = () => ws?.close()
    }
    connect()
    return () => {
      closed = true
      if (timer) clearTimeout(timer)
      ws?.close()
    }
  }, [])

  return { state, connected }
}
