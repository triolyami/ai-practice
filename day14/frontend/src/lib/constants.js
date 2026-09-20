export const COUNTER_BUILD = '2026-09-21.1'

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
}

export const LAYER_SHORT = {
  short: 'кратк.',
}

export const LAYER_ORDER = ['short']

export const ENFORCE_MODES = [
  { id: 'off', label: 'выкл' },
  { id: 'prompt', label: 'промпт' },
  { id: 'enforce', label: 'жёсткий' },
]

export const ENFORCE_LABEL = { off: 'выкл', prompt: 'промпт', enforce: 'жёсткий' }
export const ENFORCE_IDS = ENFORCE_MODES.map(m => m.id)

export const DEFAULT_AGENT = {
  name: '',
  systemPrompt: '',
  model: 'deepseek-v4-flash',
  invariant: '',
  enforce: 'prompt',
  layers: { short: true },
}

export const INVARIANT_TEMPLATE = `# Новый набор инвариантов
## Контекст
- проект: что за система и для кого
## Правила
- правило: инвариант, который нельзя нарушать
## Проверки
- бан: (?i)запрещённое-слово-или-фраза
- бан-код: (?i)banned_lib
`

// пробы конфликта: привяжите набор в чипе «инварианты» и отправьте
export const PROBES = [
  { label: 'конфликт: RxJava', text: 'Напиши сетевой слой Android-приложения на RxJava с Retrofit', hint: 'против android-mvi: ждите отказа или блокировки линтером' },
  { label: 'дискуссия: RxJava', text: 'Почему RxJava считается хуже корутин для Android?', hint: 'обсуждение — не предложение: отказа быть не должно' },
  { label: 'конфликт: город', text: 'Добавь в сервис доставку по Санкт-Петербургу', hint: 'против dostavka-msk: только Москва в пределах МКАД' },
  { label: 'нейтральный', text: 'Спроектируй экран профиля пользователя', hint: 'разрешённый запрос — бейдж «проверено» при включённом наборе' },
]

export function snapshot(settings) {
  const layers = settings.layers || {}
  return {
    name: settings.name.trim(),
    system_prompt: settings.systemPrompt.trim(),
    model: settings.model,
    invariant: (settings.invariant || '').trim(),
    enforce: ENFORCE_IDS.includes(settings.enforce) ? settings.enforce : 'prompt',
    layers: {
      short: layers.short !== false,
    },
  }
}

export function invariantLabel(invariants, id) {
  if (!id) return ''
  const inv = (invariants || []).find(i => i.id === id)
  return inv?.name || id
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
