import { MODELS, fmtLimit, fmtMoney, fmtTokens } from '../lib/constants.js'

function level(pct) {
  if (pct >= 85) return 'red'
  if (pct >= 60) return 'yellow'
  return 'green'
}

export default function TokenPanel({ metas, contextLimit, model }) {
  const last = metas.length ? metas[metas.length - 1] : null
  const t = last?.tokens
  const used = t ? t.total_est : 0
  const pct = t ? t.context_used_pct : 0
  const totals = last?.totals ?? { prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 }
  const bars = metas.map(m => m.prompt_tokens ?? m.tokens.total_est)
  const max = Math.max(...bars, 1)
  const limit = contextLimit ?? MODELS[model]?.context_limit ?? null

  return (
    <section className="tokenpanel">
      <div className="tokenpanel-in">
        <div className="tp-block">
          <span className="mini-label">контекст · {model}</span>
          <div className="gauge">
            <div
              className="gauge-fill"
              data-level={level(pct)}
              style={{ width: `${used > 0 ? Math.max(pct, 1.5) : 0}%` }}
            />
          </div>
          <span className="tp-num">
            {fmtTokens(used)} <span className="tp-sub">из {limit == null ? '—' : fmtTokens(limit)} ({pct}%)</span>
          </span>
        </div>
        <div className="tp-block">
          <span className="mini-label">всего за диалог</span>
          <span className="tp-num">
            промпт {fmtTokens(totals.prompt_tokens)} · ответ {fmtTokens(totals.completion_tokens)}
          </span>
          <span className="tp-sub">стоимость {fmtMoney(totals.cost_usd)}</span>
        </div>
        <div className="tp-block tp-spark">
          <span className="mini-label">промпт-токены по ходам (история пересылается целиком)</span>
          {bars.length > 0 ? (
            <div className="spark">
              {bars.map((v, i) => (
                <span
                  key={i}
                  style={{ height: `${Math.max((v / max) * 100, 4)}%` }}
                  title={`ход ${i + 1}: ${fmtTokens(v)} токенов`}
                />
              ))}
            </div>
          ) : (
            <span className="tp-sub">пока пусто — отправьте сообщение</span>
          )}
        </div>
      </div>
    </section>
  )
}
