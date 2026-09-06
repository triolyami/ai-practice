import { useCallback, useState } from 'react'
import { PIPELINES } from '../lib/constants.js'

const KEY = 'day3-pipelines-v1'

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (!raw || typeof raw.pipelines !== 'object' || raw.pipelines === null) return null
    return raw.pipelines
  } catch {
    return null
  }
}

export function resolveSteps(id, overrides) {
  const def = PIPELINES.find(p => p.id === id)
  if (!def) return {}
  const over = overrides?.[id] || {}
  const out = {}
  for (const st of def.steps) {
    out[st.name] = typeof over[st.name] === 'string' ? over[st.name] : st.default
  }
  return out
}

export function usePipelines() {
  const [pipelines, setPipelinesState] = useState(() => load() ?? {})

  const setPipelines = useCallback(next => {
    setPipelinesState(prev => {
      const value = typeof next === 'function' ? next(prev) : next
      try {
        localStorage.setItem(KEY, JSON.stringify({ pipelines: value }))
      } catch {}
      return value
    })
  }, [])

  const update = useCallback(
    (id, steps) => {
      setPipelines(prev => ({ ...prev, [id]: { ...(prev[id] || {}), ...steps } }))
    },
    [setPipelines],
  )

  const resetPipelines = useCallback(() => setPipelines({}), [setPipelines])

  return { pipelines, update, resetPipelines }
}
