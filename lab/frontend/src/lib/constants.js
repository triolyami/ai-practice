import { plural } from './format.js'

export const MODEL_NOTES = {
  'glm-4.6': {
    text: 'рассуждения отключены — ограничения действуют на видимый ответ',
    warn: false,
  },
  'glm-5.3': {
    text: 'всегда думает: max_tokens и stop могут сработать на скрытых рассуждениях, и видимый ответ придёт пустым',
    warn: true,
  },
}

export const VIA_LABELS = { off: 'выкл', prompt: 'промпт', api: 'API' }
export const VIAS = ['off', 'prompt', 'api']

export const FORMAT_KINDS = { json: 'JSON', markdown: 'Markdown' }

export const FORMAT_INSTRUCTIONS = {
  json: 'Ответь строго валидным JSON без markdown-ограждений и пояснений.',
  markdown: 'Оформи ответ в Markdown: заголовки, списки, выделение и блоки кода — где уместно.',
}

export const DEFAULT_SETTINGS = {
  model: 'glm-4.6',
  temperature: '0',
  format: { via: 'off', kind: 'json' },
  length: { via: 'off', words: '30', maxTokens: '60' },
  stop: { via: 'off', sequence: '\\n\\n' },
}

export function snapshot(settings) {
  return {
    model: settings.model,
    temperature: Math.max(0, Math.min(1, parseFloat(settings.temperature) || 0)),
    format: { via: settings.format.via, kind: settings.format.kind },
    length: {
      via: settings.length.via,
      words: parseInt(settings.length.words, 10) || 30,
      max_tokens: parseInt(settings.length.maxTokens, 10) || 60,
    },
    stop: { via: settings.stop.via, sequence: settings.stop.sequence },
  }
}

export function toWire(messages) {
  return messages.map(m =>
    m.role === 'user'
      ? { role: 'user', content: m.content, settings: m.settings }
      : { role: 'assistant', content: m.content },
  )
}

export function buildPayload(messages, settings) {
  return {
    model: settings.model,
    temperature: snapshot(settings).temperature,
    messages: toWire(messages),
  }
}

export function activeControlNames(s) {
  const names = []
  if (s.format.via !== 'off') names.push('формат')
  if (s.length.via !== 'off') names.push('длина')
  if (s.stop.via !== 'off') names.push('стоп')
  return names
}

export function describeSettings(s) {
  const badges = []
  const { format, length, stop } = s
  const seq = stop.sequence
  if (format.via === 'prompt') {
    badges.push({ tone: 'prompt', text: `формат: ${FORMAT_KINDS[format.kind]} — промпт` })
  }
  if (format.via === 'api') {
    badges.push({ tone: 'api', text: 'response_format: json_object — API' })
  }
  if (length.via === 'prompt') {
    badges.push({ tone: 'prompt', text: `≤ ${length.words} ${plural(length.words, ['слово', 'слова', 'слов'])} — промпт` })
  }
  if (length.via === 'api') {
    badges.push({ tone: 'api', text: `max_tokens: ${length.max_tokens} — API` })
  }
  if (stop.via === 'prompt') {
    badges.push({ tone: 'prompt', text: `стоп перед «${seq}» — промпт` })
  }
  if (stop.via === 'api') {
    badges.push({ tone: 'api', text: `stop: «${seq}» — API` })
  }
  return badges
}
