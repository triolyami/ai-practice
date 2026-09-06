import { useCallback, useRef, useState } from 'react'
import { aggregateMeta } from '../lib/answer.js'

const IDLE = {
  status: 'idle',
  text: '',
  phases: [],
  meta: null,
  error: null,
  stopped: false,
  frozen: false,
  verdict: null,
}

export function useRuns() {
  const [runs, setRuns] = useState({})
  const controllerRef = useRef(null)

  const patch = useCallback((id, p) => {
    setRuns(prev => ({ ...prev, [id]: { ...IDLE, ...(prev[id] || {}), ...p } }))
  }, [])

  const replaceAll = useCallback(next => {
    setRuns(next || {})
  }, [])

  const abort = useCallback(() => {
    controllerRef.current?.abort()
  }, [])

  const drop = useCallback(id => {
    setRuns(prev => {
      if (!(id in prev)) return prev
      const next = { ...prev }
      delete next[id]
      return next
    })
  }, [])

  const run = useCallback((item, task) => {
    const id = item.id
    patch(id, { ...IDLE, status: 'running' })
    const controller = new AbortController()
    controllerRef.current = controller

    const body =
      item.kind === 'pipeline'
        ? {
            task,
            pipeline: {
              id: item.id,
              model: item.model,
              instructions: Object.fromEntries(
                Object.entries(item.instructions || {}).filter(
                  ([, v]) => typeof v === 'string' && v.trim(),
                ),
              ),
            },
          }
        : {
            task,
            agent: { id: item.id, name: item.name, instruction: item.instruction, model: item.model },
          }

    const load = async () => {
      let phases = []
      let error = null
      let finalText = null
      let finalMeta = null

      const apply = p => patch(id, p)
      const setPhase = (name, p) => {
        phases = phases.map(ph => (ph.name === name ? { ...ph, ...p } : ph))
        apply({ phases })
      }

      try {
        const res = await fetch('/api/solve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
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
              phases = [
                ...phases.filter(ph => ph.name !== ev.step),
                { name: ev.step, content: '', meta: null, request: ev.request },
              ]
              apply({ phases })
            } else if (ev.event === 'delta') {
              phases = phases.map(ph =>
                ph.name === ev.step ? { ...ph, content: ph.content + ev.text } : ph,
              )
              apply({ phases })
            } else if (ev.event === 'phase') {
              setPhase(ev.name, { content: ev.content, meta: ev.meta })
            } else if (ev.event === 'error') {
              error = ev.message
              apply({ error })
            } else if (ev.event === 'done') {
              phases = ev.steps
              finalText = ev.content
              finalMeta = aggregateMeta(ev.steps)
              apply({ phases })
            }
          }
        }
        if (finalText !== null && !error) {
          apply({ status: 'done', text: finalText, phases, meta: finalMeta, error: null })
          return 'done'
        }
        apply({
          status: 'error',
          error: error || 'Соединение прервано до завершения ответа',
        })
        return 'error'
      } catch (err) {
        if (err.name === 'AbortError') {
          apply({ status: 'stopped', stopped: true, phases })
          return 'stopped'
        }
        apply({ status: 'error', error: err.message })
        return 'error'
      }
    }

    return load()
  }, [patch])

  return { runs, patch, replaceAll, run, abort, drop }
}
