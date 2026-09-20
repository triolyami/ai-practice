import { MODELS, fmtMoney, fmtTokens } from '../lib/constants.js'

function level(pct) {
  if (pct >= 85) return 'red'
  if (pct >= 60) return 'yellow'
  return 'green'
}

const EMPTY_BUCKET = { requests: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 }

const ROWS = [
  { key: 'chat', label: 'чат' },
  { key: 'memory_calls', label: 'обновление памяти' },
]

export default function TokenPanel({ metas, model, totals, preview }) {
  const last = metas.length ? metas[metas.length - 1] : null
  const t = last?.tokens
  const inherited = preview?.total ?? 0
  const used = t
    ? (t.total_with_answer ?? t.total_actual ?? t.total_est)
    : inherited
  const pct = t
    ? t.context_used_pct
    : (preview?.context_limit
        ? Math.min(100, Math.round(inherited / preview.context_limit * 1000) / 10)
        : 0)
  const limit = MODELS[model]?.context_limit ?? null
  const sums = totals ?? last?.totals ?? null

  return (
    <section className="tokenpanel">
      <div className="tokenpanel-in">
        <div className="tp-block" title="последний запрос + ответ на него — примерно столько займёт следующий запрос к модели">
          <span className="mini-label">контекст · {model}</span>
          <div className="gauge">
            <div
              className="gauge-fill"
              data-level={level(pct)}
              style={{ width: `${used > 0 ? Math.max(pct, 1.5) : 0}%` }}
            />
          </div>
          <span className="tp-num">
            {t?.total_with_answer == null && '≈'}{fmtTokens(used)} <span className="tp-sub">из {limit == null ? '—' : fmtTokens(limit)} ({pct}%)</span>
          </span>
        </div>
        <div className="tp-block tp-compare">
          <span className="mini-label">расход (промпт + ответ · стоимость)</span>
          {sums ? (
            <table className="tp-table">
              <tbody>
                {ROWS.map(({ key, label }) => {
                  const b = sums[key] ?? EMPTY_BUCKET
                  return (
                    <tr key={key} className={key === 'memory_calls' ? 'tp-row--summary' : ''}>
                      <td>{label}</td>
                      <td>{fmtTokens(b.prompt_tokens)} + {fmtTokens(b.completion_tokens)}</td>
                      <td>{fmtMoney(b.cost_usd)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <span className="tp-sub">пока пусто — отправьте сообщение</span>
          )}
        </div>
      </div>
    </section>
  )
}
