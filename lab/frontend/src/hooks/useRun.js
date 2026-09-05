import { useCallback, useEffect, useRef, useState } from 'react'

const IDLE = {
  phase: 'idle',
  variants: [],
  groups: {},
  meta: null,
  runs: {},
  delivered: 0,
  elapsed: '',
  error: null,
}

export function useRun() {
  const [run, setRun] = useState(IDLE)
  const controllerRef = useRef(null)
  const timerRef = useRef(null)
  const startedAtRef = useRef(0)

  useEffect(() => () => {
    controllerRef.current?.abort()
    clearInterval(timerRef.current)
  }, [])

  const finish = useCallback((phase, patch = {}) => {
    clearInterval(timerRef.current)
    timerRef.current = null
    setRun(prev => ({ ...prev, phase, ...patch }))
  }, [])

  const start = useCallback(async (config) => {
    if (controllerRef.current) controllerRef.current.abort()
    clearInterval(timerRef.current)
    const controller = new AbortController()
    controllerRef.current = controller
    startedAtRef.current = performance.now()
    setRun({ ...IDLE, phase: 'running' })

    let sawDone = false
    const handle = (ev) => {
      if (ev.event === 'start') {
        setRun(prev => ({ ...prev, variants: ev.variants, groups: ev.groups, meta: ev.meta }))
        timerRef.current = setInterval(() => {
          const seconds = ((performance.now() - startedAtRef.current) / 1000).toFixed(1)
          setRun(prev => ({ ...prev, elapsed: `${seconds} с` }))
        }, 100)
      } else if (ev.event === 'result') {
        setRun(prev => ({
          ...prev,
          delivered: ev.delivered,
          runs: { ...prev.runs, [ev.run.id]: ev.run },
        }))
      } else if (ev.event === 'error') {
        setRun(prev => ({ ...prev, error: ev.message }))
      } else if (ev.event === 'done') {
        sawDone = true
        finish('done', { elapsed: `${ev.elapsed_s} с` })
      }
    }

    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
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
      if (!sawDone) finish('failed', { error: 'Соединение прервано до завершения прогона' })
    } catch (err) {
      if (err.name === 'AbortError') finish('stopped')
      else finish('failed', { error: err.message })
    }
  }, [finish])

  const stop = useCallback(() => {
    controllerRef.current?.abort()
  }, [])

  return { run, start, stop }
}
