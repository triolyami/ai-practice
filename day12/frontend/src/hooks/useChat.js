import { useCallback, useRef, useState } from 'react'

const IDLE = { phase: 'idle', text: '', meta: null, error: null, request: null, steps: [] }

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
    let steps = []

    const setStep = (i, patch) => {
      steps = steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s))
      setChat(prev => ({ ...prev, steps }))
    }

    const handle = (ev) => {
      if (ev.event === 'start') {
        request = ev.request
        if (ev.meta?.pipeline?.length) {
          steps = ev.meta.pipeline.map(name => ({ name, text: '', done: false }))
          setChat(prev => ({ ...prev, request: ev.request, steps }))
        } else {
          setChat(prev => ({ ...prev, request: ev.request }))
        }
      } else if (ev.event === 'step_start') {
        if (!steps[ev.step]) steps = [...steps]
        steps[ev.step] = steps[ev.step]
          ? { ...steps[ev.step], name: ev.name }
          : { name: ev.name, text: '', done: false }
        setChat(prev => ({ ...prev, steps: [...steps] }))
      } else if (ev.event === 'delta') {
        if (ev.step != null && steps[ev.step]) {
          setStep(ev.step, { text: (steps[ev.step].text || '') + ev.text })
        } else {
          text += ev.text
          setChat(prev => ({ ...prev, text }))
        }
      } else if (ev.event === 'step_done') {
        setStep(ev.step, {
          done: true,
          text: ev.content ?? steps[ev.step]?.text ?? '',
          prompt_tokens: ev.prompt_tokens,
          completion_tokens: ev.completion_tokens,
        })
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
      if (meta) final = { phase: 'done', text, meta, error: null, request, steps }
      else if (error) final = { phase: 'error', text, meta: null, error, request, steps }
      else final = { phase: 'error', text, meta: null, error: 'Соединение прервано до завершения ответа', request, steps }
    } catch (err) {
      if (err.name === 'AbortError') final = { phase: 'stopped', text, meta: null, error: null, request, steps }
      else final = { phase: 'error', text, meta: null, error: err.message, request, steps }
    }
    setChat(final)
    onFinished?.(final)
  }, [abort])

  return { chat, send, abort, reset }
}
