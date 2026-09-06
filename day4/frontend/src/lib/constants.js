export const DEFAULT_PROMPT =
  'Придумай три запоминающихся названия для кофейни и объясни каждое одним предложением. ' +
  'В конце ответь на два коротких вопроса, каждый — с новой строки: ' +
  'какая планета ближе всего к Солнцу и сколько будет 17 × 23.'

export const FACT_CHECKS = [
  { label: 'Меркурий', pattern: 'меркурий' },
  { label: '391', pattern: '391' },
]

export const MODELS = {
  'glm-4.6': {
    label: 'glm-4.6',
    thinking: 'off',
    note: 'рассуждения отключены — температура влияет только на выбор слов',
    defaultTemperatures: [0, 0.7, 1.0],
    cap: 'Z.ai отклоняет температуру выше 1 для glm-4.6 — ошибка 1210 «ограничение числового диапазона [0,1]». Прогоны выше 1 у этой модели завершатся ошибкой API.',
  },
  'glm-5.3': {
    label: 'glm-5.3',
    thinking: 'effort',
    note: 'всегда думает — усилие рассуждения выбирается ниже и тоже влияет на ответ',
    defaultTemperatures: [0, 0.7, 1.2],
    cap: 'glm-5.3 принимает значения выше 1 — задание с t=1.2 выполняется на нём буквально.',
  },
}

export const EFFORTS = ['low', 'high', 'max']
export const MAX_PARALLEL = 4
export const MIN_TEMPERATURE_POINTS = 1
export const MAX_TEMPERATURE_POINTS = 4
export const NEW_TEMPERATURE = '0.5'

export function parseTemp(raw) {
  const n = Number(String(raw).trim().replace(',', '.'))
  return Number.isFinite(n) && n >= 0 && n <= 2 ? n : null
}

export function laneTemperatures(inputs) {
  const out = []
  for (const raw of inputs) {
    const n = parseTemp(raw)
    if (n != null && !out.includes(n)) out.push(n)
  }
  return out
}

export const TEMPERATURE_HINTS = {
  0: 'минимум случайности',
  0.7: 'обычный чат-режим',
  1.0: 'максимум для glm-4.6',
  1.2: 'задание: максимум вариативности',
}
