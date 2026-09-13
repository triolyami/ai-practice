import { MODELS, STRATEGY_MODES, fmtMoney, fmtTokens } from '../lib/constants.js'

function level(pct) {
  if (pct >= 85) return 'red'
  if (pct >= 60) return 'yellow'
  return 'green'
}

const EMPTY_BUCKET = { requests: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 }

export default function TokenPanel({ metas, model, totals }) {
  const last = metas.length ? metas[metas.length - 1] : null
  const t = last?.tokens
  const used = t ? (t.total_with_answer ?? t.total_actual ?? t.total_est) : 0
  const pct = t ? t.context_used_pct : 0
  const limit = MODELS[model]?.context_limit ?? null
  const byMode = totals ?? last?.totals ?? null
  const factsCalls = byMode?.facts_calls

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
          <span className="mini-label">расход по стратегиям (промпт + ответ · стоимость)</span>
          {byMode ? (
            <table className="tp-table">
              <tbody>
                {Object.entries(STRATEGY_MODES).map(([mode, label]) => {
                  const b = byMode[mode] ?? EMPTY_BUCKET
                  return (
                    <tr key={mode} className={last?.strategy === mode ? 'tp-row--on' : ''}>
                      <td>{label}</td>
                      <td>{fmtTokens(b.prompt_tokens)} + {fmtTokens(b.completion_tokens)}</td>
                      <td>{fmtMoney(b.cost_usd)}</td>
                    </tr>
                  )
                })}
                {factsCalls && (
                  <tr className="tp-row--summary" title="отдельные вызовы модели на обновление блока фактов">
                    <td>обновление фактов</td>
                    <td>{factsCalls.requests} · {fmtTokens(factsCalls.prompt_tokens)} + {fmtTokens(factsCalls.completion_tokens)}</td>
                    <td>{fmtMoney(factsCalls.cost_usd)}</td>
                  </tr>
                )}
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
