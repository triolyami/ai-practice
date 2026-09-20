export const COUNTER_BUILD = '2026-09-20.2'

export const MODELS = {  'deepseek-v4-flash': {
    note: 'быстрая, рассуждает сама — текущий выбор по умолчанию',
    warn: false,
    context_limit: 1000000,
    price_in: 0.15,
    price_out: 0.6,
  },
  'deepseek-v4-pro': {
    note: 'старшая: отвечает глубже, но медленнее и дороже',
    warn: false,
    context_limit: 1000000,
    price_in: 0.66,
    price_out: 1.98,
  },
  'glm-4.6': {
    note: 'быстрая, рассуждения отключены — нужен баланс Z.ai',
    warn: false,
    context_limit: 200000,
    price_in: 0.6,
    price_out: 2.2,
  },
  'glm-5.3': {
    note: 'всегда думает: глубже, но медленнее — нужен баланс Z.ai',
    warn: false,
    context_limit: 1000000,
    price_in: 1.4,
    price_out: 4.4,
  },
}

export const MODEL_NOTES = MODELS

export const LAYERS = {
  short: 'краткосрочная',
  working: 'рабочая',
  longterm: 'долговременная',
}

export const LAYER_SHORT = {
  short: 'кратк.',
  working: 'раб.',
  longterm: 'долг.',
}

export const LAYER_ORDER = ['short', 'working', 'longterm']

export const DEFAULT_AGENT = {
  name: '',
  systemPrompt: '',
  model: 'deepseek-v4-flash',
  workspace: '',
  layers: { short: true, working: true, longterm: true },
}

export function snapshot(settings) {
  const layers = settings.layers || {}
  return {
    name: settings.name.trim(),
    system_prompt: settings.systemPrompt.trim(),
    model: settings.model,
    workspace: (settings.workspace || '').trim(),
    layers: {
      short: layers.short !== false,
      working: layers.working !== false,
      longterm: layers.longterm !== false,
    },
  }
}

export function fmtTokens(n) {
  return n == null ? '—' : Number(n).toLocaleString('ru-RU')
}

export function fmtMoney(c) {
  return c == null ? '—' : '$' + Number(c).toFixed(4)
}

export function fmtLimit(n) {
  return n >= 1000000 ? `${n / 1000000}M` : `${Math.round(n / 1000)}K`
}
