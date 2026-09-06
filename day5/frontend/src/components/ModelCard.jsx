import { IDLE } from '../hooks/useRuns.js'

function fmtMs(ms) {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} с` : `${ms} мс`
}

function fmtCost(cost) {
  if (cost == null) return '—'
  return cost === 0 ? '$0' : `$${cost.toFixed(6)}`
}

export default function ModelCard({ model, spec, run, busy, judged, onRerun }) {
  const meta = run.meta || {}
  const verdict = judged?.ranking.find(r => r.id === model)
  const isBest = judged?.best === model
  return (
    <article className={`sample${run.status === 'running' ? ' sample--running' : ''}`}>
      <div className="sample-head">
        <div className="model-name">
          <span className={`tier tier--${spec.tier}`}>{spec.tierName}</span>
          <span className="model-label">{spec.label}</span>
        </div>
        {isBest ? <span className="badge badge--ok">лучший по версии судьи</span> : null}
      </div>
      {run.status === 'error' ? (
        <p className="errtext">{run.error}</p>
      ) : run.text ? (
        <div className="sample-text">{run.text}</div>
      ) : (
        <p className="answer-empty">
          {run.status === 'running' ? 'генерация…' : 'ещё не запущена'}
        </p>
      )}
      {verdict ? (
        <div className="judge-line">
          <span className={`badge ${verdict.score >= 7 ? 'badge--ok' : verdict.score >= 4 ? 'badge--mid' : 'badge--no'}`}>
            {verdict.score == null ? '—' : `${verdict.score}/10`}
          </span>
          <span className="judge-comment">{verdict.comment}</span>
        </div>
      ) : null}
      <div className="sample-foot">
        <span className="meta">
          первый токен {fmtMs(meta.ttft_ms)} · всего {fmtMs(meta.latency_ms)} ·{' '}
          {meta.completion_tokens != null ? `${meta.completion_tokens} токенов` : '—'} ·{' '}
          {fmtCost(meta.cost_usd)}
          {meta.finish_reason ? ` · ${meta.finish_reason}` : ''}
        </span>
        <button
          type="button"
          className="chip-btn btn--sm"
          disabled={busy}
          onClick={() => onRerun(model)}
        >
          перезапустить
        </button>
      </div>
    </article>
  )
}

export function modelRun(models, runs, id) {
  return runs[id] || { ...IDLE }
}
