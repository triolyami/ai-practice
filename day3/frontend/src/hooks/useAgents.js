import { useCallback, useState } from 'react'
import { DEFAULT_AGENTS } from '../lib/constants.js'

const KEY = 'day3-agents-v1'

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (!Array.isArray(raw?.agents)) return null
    const agents = raw.agents
      .filter(a => a && typeof a.id === 'string' && typeof a.name === 'string')
      .map(a => ({
        id: a.id,
        name: a.name,
        instruction: typeof a.instruction === 'string' ? a.instruction : '',
        model: a.model === 'glm-5.3' ? 'glm-5.3' : 'glm-4.6',
      }))
    return agents.length ? agents : null
  } catch {
    return null
  }
}

export function useAgents() {
  const [agents, setAgentsState] = useState(() => load() ?? DEFAULT_AGENTS.map(a => ({ ...a })))

  const setAgents = useCallback(next => {
    setAgentsState(prev => {
      const value = typeof next === 'function' ? next(prev) : next
      try {
        localStorage.setItem(KEY, JSON.stringify({ agents: value }))
      } catch {}
      return value
    })
  }, [])

  return { agents, setAgents }
}
