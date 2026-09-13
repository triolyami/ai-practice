import { DEFAULT_AGENT, MODEL_NOTES, STRATEGY_MODES } from './constants.js'

const CHATS_KEY = 'day10-chats-v1'
const AGENT_KEY = 'day10-agent-v1'
const SETTINGS_OPEN_KEY = 'day10-settings-open-v1'
export const MAX_CHATS = 50

export function loadChats() {
  try {
    const raw = JSON.parse(localStorage.getItem(CHATS_KEY) || 'null')
    if (!Array.isArray(raw)) return []
    return raw.filter(c => c && typeof c.id === 'string')
  } catch {
    return []
  }
}

export function saveChats(chats) {
  try {
    localStorage.setItem(CHATS_KEY, JSON.stringify(chats))
  } catch {}
}

export function loadAgent() {
  try {
    const raw = JSON.parse(localStorage.getItem(AGENT_KEY) || 'null')
    if (!raw || typeof raw !== 'object') return { ...DEFAULT_AGENT }
    const size = Number(raw.windowSize)
    return {
      name: typeof raw.name === 'string' ? raw.name : '',
      systemPrompt: typeof raw.systemPrompt === 'string' ? raw.systemPrompt : '',
      model: raw.model in MODEL_NOTES ? raw.model : DEFAULT_AGENT.model,
      strategy: raw.strategy in STRATEGY_MODES ? raw.strategy : DEFAULT_AGENT.strategy,
      windowSize: Number.isFinite(size) ? Math.min(50, Math.max(2, Math.round(size))) : DEFAULT_AGENT.windowSize,
    }
  } catch {
    return { ...DEFAULT_AGENT }
  }
}

export function saveAgent(settings) {
  try {
    localStorage.setItem(AGENT_KEY, JSON.stringify(settings))
  } catch {}
}

export function loadSettingsOpen() {
  try {
    const raw = JSON.parse(localStorage.getItem(SETTINGS_OPEN_KEY) || 'null')
    return typeof raw === 'boolean' ? raw : false
  } catch {
    return false
  }
}

export function saveSettingsOpen(open) {
  try {
    localStorage.setItem(SETTINGS_OPEN_KEY, JSON.stringify(open))
  } catch {}
}
