import { PEOPLE } from './constants.js'

const KEYWORD_RE =
  /(?<![а-яё])(финальное решение группы|финальное решение|финальный ответ группы|финальный ответ|итоговый ответ|окончательный ответ|ответ группы|финальный итог|итог|ответ)(?![а-яё])/i
const LABEL_PREFIX_RE = /^[\s>#*_"'«»`(|[\]~—–\-.,;:0-9]*$/
const LEADING_JUNK_RE = /^[\s:;.,)"'»\]+}*#_—–-]+/
const ANY_AGE_RE = /\b(25|28|31|34)\b/

function isLabelOnly(line) {
  const m = line.match(KEYWORD_RE)
  if (!m) return false
  if (!LABEL_PREFIX_RE.test(line.slice(0, m.index))) return false
  return !line.slice(m.index + m[0].length).replace(LEADING_JUNK_RE, '').trim()
}

function lastBlock(lines) {
  let end = lines.length - 1
  for (;;) {
    while (end >= 0 && !lines[end].trim()) end--
    if (end < 0) return null
    if (!isLabelOnly(lines[end])) break
    end--
  }
  let start = end
  while (start > 0 && lines[start - 1].trim()) start--
  return lines.slice(start, end + 1).join('\n').trim() || null
}

export function extractAnswer(text) {
  if (!text) return null
  const lines = text.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = lines[i].match(KEYWORD_RE)
    if (!m) continue
    if (!LABEL_PREFIX_RE.test(lines[i].slice(0, m.index))) continue
    const tail = lines[i].slice(m.index + m[0].length).replace(LEADING_JUNK_RE, '').trim()
    const rest = lines.slice(i + 1).join('\n').trim()
    if (tail || rest) return [tail, rest].filter(Boolean).join('\n')
  }
  return lastBlock(lines)
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
    effort: last.meta?.effort || null,
    steps: phasesList.length,
    prompt_tokens: phasesList.length ? sum('prompt_tokens') : null,
    completion_tokens: phasesList.length ? sum('completion_tokens') : null,
    latency_ms: phasesList.length ? sum('latency_ms') : null,
  }
}
