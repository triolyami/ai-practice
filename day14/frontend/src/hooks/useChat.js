import { useCallback, useRef, useState } from 'react'

const IDLE = { phase: 'idle', text: '', meta: null, error: null, request: null, blocked: [] }

export function useChat() {
  const [chat, setChat] = useState(IDLE)
  const controllerRef = useRef(null)

  const abort = useCallback(() => {
    controllerRef.current?.abort()
  }, [])

  const reset = useCallback(() => {
    abort()
    setChat(IDLE)
  }, [abort])

  const send = useCallback(async (payload, onFinished, onEvent) => {
    abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setChat({ ...IDLE, phase: 'running' })

    let text = ''
    let meta = null
    let error = null
    let request = null
    let blocked = []

    const handle = (ev) => {
      if (ev.event === 'start') {
        request = ev.request
        setChat(prev => ({ ...prev, request: ev.request }))
      } else if (ev.event === 'delta') {
        text += ev.text
        setChat(prev => ({ ...prev, text }))
      } else if (ev.event === 'violation') {
        // текущая попытка уходит в «заблокировано», ретрай стримится заново
        blocked = [...blocked, { content: ev.content ?? text, violations: ev.violations || [] }]
        text = ''
        setChat(prev => ({ ...prev, blocked, text: '' }))
      } else if (ev.event === 'error') {
        error = ev.message
      } else if (ev.event === 'done') {
        meta = ev.meta || {}
        text = ev.content
      }
      onEvent?.(ev)
    }

    let final
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
      if (!res.ok) {
        const j = await res.json().catch(() => ({}))
        throw new Error(j.error || `HTTP ${res.status}`)
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, idx).trim()
          buf = buf.slice(idx + 1)
          if (line) handle(JSON.parse(line))
        }
      }
      if (meta) final = { phase: 'done', text, meta, error: null, request, blocked }
      else if (error) final = { phase: 'error', text, meta: null, error, request, blocked }
      else final = { phase: 'error', text, meta: null, error: 'Соединение прервано до завершения ответа', request, blocked }
    } catch (err) {
      if (err.name === 'AbortError') final = { phase: 'stopped', text, meta: null, error: null, request, blocked }
      else final = { phase: 'error', text, meta: null, error: err.message, request, blocked }
    }
    setChat(final)
    onFinished?.(final)
  }, [abort])

  return { chat, send, abort, reset }
}
