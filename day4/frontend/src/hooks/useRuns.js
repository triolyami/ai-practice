import { useCallback, useRef, useState } from 'react'
import { MAX_PARALLEL } from '../lib/constants.js'

export const IDLE = { status: 'idle', text: '', meta: null, error: null, seeded: false }

export function runId(model, temperature, sample) {
  return `${model}|${temperature}|${sample}`
}

export function useRuns() {
  const [runs, setRuns] = useState({})
  const [job, setJob] = useState(null)
  const controllersRef = useRef(new Map())

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
    for (const controller of controllersRef.current.values()) controller.abort()
  }, [])

  const runOne = useCallback(
    (model, temperature, sample, prompt, effort) => {
      const id = runId(model, temperature, sample)
      patch(id, { ...IDLE, status: 'running' })
      const controller = new AbortController()
      const prev = controllersRef.current.get(id)
      if (prev) prev.abort()
      controllersRef.current.set(id, controller)

      const load = async () => {
        try {
          const res = await fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, model, temperature, effort }),
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
        } finally {
          if (controllersRef.current.get(id) === controller) controllersRef.current.delete(id)
        }
      }

      return load()
    },
    [append, patch],
  )

  const runAll = useCallback(
    async (model, temperatures, samples, prompt, effort) => {
      const tasks = []
      for (const temperature of temperatures)
        for (let sample = 1; sample <= samples; sample++) tasks.push({ temperature, sample })
      const total = tasks.length
      setJob({ total, done: 0, label: '' })
      let done = 0
      let active = 0
      let stopped = false

      const worker = async () => {
        for (;;) {
          if (stopped) return
          const task = tasks.shift()
          if (!task) return
          active++
          setJob({ total, done, label: `параллельно ${active}` })
          const status = await runOne(model, task.temperature, task.sample, prompt, effort)
          active--
          done++
          setJob({ total, done, label: `параллельно ${active}` })
          if (status === 'stopped') stopped = true
        }
      }

      await Promise.all(Array.from({ length: Math.min(MAX_PARALLEL, total) }, worker))
      setJob(null)
    },
    [runOne],
  )

  return { runs, patch, replaceAll, runOne, runAll, stop, job }
}
