import { useCallback, useRef, useState } from 'react'

export const IDLE = { status: 'idle', text: '', meta: null, error: null, seeded: false }

export function runId(model, temperature, sample) {
  return `${model}|${temperature}|${sample}`
}

export function useRuns() {
  const [runs, setRuns] = useState({})
  const [job, setJob] = useState(null)
  const abortRef = useRef(null)

  const patch = useCallback((id, p) => {
    setRuns(prev => ({ ...prev, [id]: { ...IDLE, ...(prev[id] || {}), ...p } }))
  }, [])

  const append = useCallback((id, text) => {
    setRuns(prev => {
      const cur = prev[id] || IDLE
      return { ...prev, [id]: { ...IDLE, ...cur, text: cur.text + text } }
    })
  }, [])

  const replaceAll = useCallback(next => setRuns(next || {}), [])

  const stop = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
  }, [])

  const runOne = useCallback(
    (model, temperature, sample, prompt) => {
      const id = runId(model, temperature, sample)
      patch(id, { ...IDLE, status: 'running' })
      const controller = new AbortController()
      abortRef.current = controller

      const load = async () => {
        try {
          const res = await fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, model, temperature }),
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
              if (!line) continue
              const ev = JSON.parse(line)
              if (ev.event === 'start') {
                patch(id, { meta: ev.meta })
              } else if (ev.event === 'delta') {
                append(id, ev.text)
              } else if (ev.event === 'done') {
                patch(id, { status: 'done', text: ev.content, meta: ev.meta })
                return 'done'
              } else if (ev.event === 'error') {
                patch(id, { status: 'error', error: ev.message })
                return 'error'
              }
            }
          }
          patch(id, { status: 'error', error: 'Соединение прервано до завершения ответа' })
          return 'error'
        } catch (err) {
          if (err.name === 'AbortError') {
            patch(id, { status: 'stopped', error: null })
            return 'stopped'
          }
          patch(id, { status: 'error', error: err.message })
          return 'error'
        }
      }

      return load()
    },
    [append, patch],
  )

  const runAll = useCallback(
    async (model, temperatures, samples, prompt) => {
      const total = temperatures.length * samples
      let doneCount = 0
      setJob({ total, done: 0, label: '' })
      let aborted = false
      for (const temperature of temperatures) {
        if (aborted) break
        for (let sample = 1; sample <= samples; sample++) {
          if (aborted) break
          setJob({ total, done: doneCount, label: `t=${temperature} · №${sample}` })
          const status = await runOne(model, temperature, sample, prompt)
          doneCount++
          if (status === 'stopped') aborted = true
        }
      }
      setJob(null)
    },
    [runOne],
  )

  return { runs, patch, replaceAll, runOne, runAll, stop, job }
}
