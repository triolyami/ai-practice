import { DEFAULT_AGENT, MODEL_NOTES, LAYER_ORDER } from './constants.js'

const CHATS_KEY = 'day12-chats-v1'
const AGENT_KEY = 'day12-agent-v1'
const SETTINGS_OPEN_KEY = 'day12-settings-open-v1'
export const MAX_CHATS = 50

export function loadChats() {
  try {
    const raw = JSON.parse(localStorage.getItem(CHATS_KEY) || 'null')
    if (!Array.isArray(raw)) return []
    return raw
      .filter(c => c && typeof c.id === 'string')
      .map(c => ({
        ...c,
        profile: typeof c.profile === 'string' ? c.profile : '',
      }))
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
    const layers = raw.layers && typeof raw.layers === 'object' ? raw.layers : {}
    return {
      name: typeof raw.name === 'string' ? raw.name : '',
      systemPrompt: typeof raw.systemPrompt === 'string' ? raw.systemPrompt : '',
      model: raw.model in MODEL_NOTES ? raw.model : DEFAULT_AGENT.model,
      profile: typeof raw.profile === 'string' ? raw.profile.slice(0, 80) : '',
      layers: Object.fromEntries(
        LAYER_ORDER.map(k => [k, layers[k] !== false])
      ),
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
