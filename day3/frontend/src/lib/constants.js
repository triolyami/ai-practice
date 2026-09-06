export const TASK = `Четыре коллеги — Анна, Борис, Вера и Григорий — живут в четырёх разных городах: Москва, Казань, Пермь и Сочи. Возраст каждого — 25, 28, 31 или 34 года, и у всех он разный. Известно:

1. Вера живёт в Казани.
2. Тот, кто живёт в Сочи, — самый старший из четырёх.
3. Житель Перми на 6 лет младше жителя Сочи.
4. Борис старше Григория.
5. Вера ровно на 3 года младше Анны.
6. Анна живёт не в Сочи и не в Москве.

Определите, кто в каком городе живёт и сколько лет каждому.`

export const DEFAULT_TASK = TASK

export const GROUND_TRUTH = 'Анна — Пермь, 28; Борис — Сочи, 34; Вера — Казань, 25; Григорий — Москва, 31.'

export const STRATEGIES = [
  { id: 'baseline', title: 'Прямой ответ', chip: 'прямой ответ', hint: 'задача без дополнительных инструкций', model: 'glm-4.6', main: true },
  { id: 'cot', title: 'Пошагово', chip: 'пошагово', hint: 'в промпт добавлена инструкция «решай пошагово»', model: 'glm-4.6', main: true },
  { id: 'meta', title: 'Сначала промпт', chip: 'сначала промпт', hint: 'модель сначала пишет промпт для решения, затем решает по нему', model: 'glm-4.6', main: true },
  { id: 'experts', title: 'Группа экспертов', chip: 'группа экспертов', hint: 'аналитик, инженер и критик решают в одном запросе', model: 'glm-4.6', main: true },
  { id: 'experts_multi', title: 'Эксперты по очереди', chip: 'эксперты по очереди', hint: 'доп.: отдельный запрос каждому эксперту, затем синтез', model: 'glm-4.6', main: false },
  { id: 'thinking', title: 'Нативное рассуждение', chip: 'нативное рассуждение · 5.3', hint: 'доп.: glm-5.3 думает сам, без промпт-трюков', model: 'glm-5.3', main: false },
]

export const MAIN_ORDER = ['baseline', 'cot', 'meta', 'experts']
export const EXTRA_ORDER = ['experts_multi', 'thinking']

export const STEP_LABELS = {
  solve: 'решение',
  compose: 'промпт, который написала модель',
  analytik: 'аналитик',
  inzhener: 'инженер',
  kritik: 'критик',
  synthesis: 'синтез группы',
}

function stem(stems) {
  return new RegExp(stems)
}

function ageRe(age) {
  return new RegExp(`\\b${age}\\b`)
}

export const PEOPLE = [
  { name: 'Анна', city: 'Пермь', age: 28, nameRe: /(?<![а-яё])анн/, cityRe: stem('перм'), otherCityRe: stem('москв|казан|соч'), ageRe: ageRe(28) },
  { name: 'Борис', city: 'Сочи', age: 34, nameRe: /(?<![а-яё])борис/, cityRe: stem('соч'), otherCityRe: stem('москв|казан|перм'), ageRe: ageRe(34) },
  { name: 'Вера', city: 'Казань', age: 25, nameRe: /(?<![а-яё])вер[аыеой](?![а-яё])/, cityRe: stem('казан'), otherCityRe: stem('москв|перм|соч'), ageRe: ageRe(25) },
  { name: 'Григорий', city: 'Москва', age: 31, nameRe: /(?<![а-яё])григор/, cityRe: stem('москв'), otherCityRe: stem('казан|перм|соч'), ageRe: ageRe(31) },
]
