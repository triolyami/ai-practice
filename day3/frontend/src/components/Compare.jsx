import { extractAnswer, verdictFor } from '../lib/answer.js'
import { truncate } from '../lib/format.js'
import { DEFAULT_TASK, GROUND_TRUTH } from '../lib/constants.js'

function normAnswer(text) {
  if (!text) return ''
  const firstLine = text.split('\n')[0] || ''
  return firstLine.toLowerCase().replace(/[\s.!,;:«»"')(-]+/g, '').slice(0, 60)
}

const VERDICT_CELL = {
  true: { cls: 'badge--ok', text: 'да' },
  false: { cls: 'badge--no', text: 'нет' },
  null: { cls: 'badge--unk', text: '?' },
}

export default function Compare({ runs, task, universe, selected }) {
  const done = universe.filter(u => selected.includes(u.id) && runs[u.id]?.status === 'done')
  if (done.length < 2) return null

  const builtIn = task.trim() === DEFAULT_TASK.trim()
  const rows = done.map(u => {
    const state = runs[u.id]
    return {
      id: u.id,
      name: u.name || 'без названия',
      answer: extractAnswer(state.text),
      verdict: verdictFor(state, builtIn),
      meta: state.meta,
    }
  })

  const judged = rows.filter(r => r.verdict != null)
  const okCount = judged.filter(r => r.verdict === true).length
  const answers = rows.map(r => normAnswer(r.answer)).filter(Boolean)
  const sameAnswers = answers.length > 1 && new Set(answers).size === 1

  return (
    <section className="compare">
      <span className="side-title">сравнение</span>
      <p className="compare-note">
        финальный ответ извлекается из текста решения по слову «ответ»; эталон
        для встроенной задачи: {GROUND_TRUTH}
      </p>
      <table className="cmp-table">
        <thead>
          <tr>
            <th>агент</th>
            <th>финальный ответ</th>
            {builtIn && <th>совпало</th>}
            <th>время · токены</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const cell = VERDICT_CELL[r.verdict === true ? 'true' : r.verdict === false ? 'false' : 'null']
            return (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td className="cmp-answer" title={r.answer || ''}>
                  {r.answer
                    ? truncate(r.answer.replace(/\n+/g, ' ').replace(/[*#`$]+/g, ''), 140)
                    : '—'}
                </td>
                {builtIn && (
                  <td>
                    <span className={`badge ${cell.cls}`}>{cell.text}</span>
                  </td>
                )}
                <td className="cmp-mono">
                  {r.meta?.latency_ms != null ? `${(r.meta.latency_ms / 1000).toFixed(1)} с` : '—'}
                  {' · '}
                  {r.meta?.completion_tokens != null ? `${r.meta.completion_tokens} ток.` : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="compare-concl">
        {builtIn
          ? `с эталоном совпали ответы у ${okCount} из ${judged.length} агентов.`
          : 'задача не встроенная — сверка с эталоном недоступна, сравните решения глазами.'}
        {answers.length > 1 &&
          (sameAnswers
            ? ' финальные ответы текстуально совпадают.'
            : ' финальные ответы текстуально различаются — форма подачи у моделей разная, верность определяет колонка «совпало» и сами решения выше.')}
      </p>
    </section>
  )
}
