import { PEOPLE } from './constants.js'

const KEYWORD_RE = /(?<![а-яё])(финальное решение группы|финальное решение|финальный ответ группы|финальный ответ|итоговый ответ|ответ группы|ответ)(?![а-яё])/gi
const ANY_AGE_RE = /\b(25|28|31|34)\b/

export function extractAnswer(text) {
  if (!text) return null
  let last = null
  let m
  while ((m = KEYWORD_RE.exec(text)) !== null) last = m
  KEYWORD_RE.lastIndex = 0
  if (!last) return null
  const rest = text
    .slice(last.index + last[0].length)
    .replace(/^[\s:—–#*_\-»«"]+/, '')
    .trim()
  return rest || null
}

export function checkVerdict(text) {
  if (!text) return null
  const norm = text.toLowerCase().replace(/ё/g, 'е')
  const segments = norm.split(/\n+|;\s*/)
  const results = PEOPLE.map(p => {
    const cands = segments.filter(s => p.nameRe.test(s))
    if (!cands.length) return null
    const good = cands.some(s => p.cityRe.test(s) && p.ageRe.test(s))
    if (good) return true
    const bad = cands.some(s => p.otherCityRe.test(s) || (ANY_AGE_RE.test(s) && !p.ageRe.test(s)))
    return bad ? false : null
  })
  if (results.every(r => r === true)) return true
  if (results.some(r => r === false)) return false
  return null
}

export function verdictFor(state, builtIn) {
  if (!builtIn) return null
  if (state.verdict != null) return state.verdict
  if (state.status === 'done') return checkVerdict(state.text)
  return null
}

export function aggregateMeta(phases) {
  const phasesList = phases || []
  const last = phasesList[phasesList.length - 1] || {}
  const sum = key => phasesList.reduce((acc, p) => acc + (p.meta?.[key] || 0), 0)
  return {
    model: last.meta?.model,
    finish_reason: last.meta?.finish_reason,
    steps: phasesList.length,
    prompt_tokens: phasesList.length ? sum('prompt_tokens') : null,
    completion_tokens: phasesList.length ? sum('completion_tokens') : null,
    latency_ms: phasesList.length ? sum('latency_ms') : null,
  }
}
