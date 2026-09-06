import { DEFAULT_SETTINGS, FORMAT_KINDS, MODEL_NOTES, VIAS } from './constants.js'

const CHATS_KEY = 'lab-chats-v1'
const SETTINGS_KEY = 'lab-settings-v1'
export const MAX_CHATS = 50

export function loadChats() {
  try {
    const raw = JSON.parse(localStorage.getItem(CHATS_KEY) || 'null')
    if (!Array.isArray(raw)) return []
    return raw.filter(c => c && typeof c.id === 'string' && Array.isArray(c.messages))
  } catch {
    return []
  }
}

export function saveChats(chats) {
  try {
    localStorage.setItem(CHATS_KEY, JSON.stringify(chats))
  } catch {}
}

function pickVia(v) {
  return VIAS.includes(v) ? v : 'off'
}

export function loadSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem(SETTINGS_KEY) || 'null')
    if (!raw || typeof raw !== 'object') return DEFAULT_SETTINGS
    return {
      model: raw.model in MODEL_NOTES ? raw.model : DEFAULT_SETTINGS.model,
      temperature: String(Math.max(0, Math.min(1, parseFloat(raw.temperature) || 0))),
      format: {
        via: pickVia(raw.format?.via),
        kind: raw.format?.kind in FORMAT_KINDS ? raw.format.kind : DEFAULT_SETTINGS.format.kind,
      },
      length: {
        via: pickVia(raw.length?.via),
        words: String(parseInt(raw.length?.words, 10) || 30),
        maxTokens: String(parseInt(raw.length?.maxTokens, 10) || 60),
      },
      stop: {
        via: pickVia(raw.stop?.via),
        sequence: typeof raw.stop?.sequence === 'string'
          ? raw.stop.sequence
          : DEFAULT_SETTINGS.stop.sequence,
      },
    }
  } catch {
    return DEFAULT_SETTINGS
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch {}
}
