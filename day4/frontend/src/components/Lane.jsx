import { checkFacts, laneSummary, diversityLabel } from '../lib/metrics.js'
import { FACT_CHECKS, TEMPERATURE_HINTS } from '../lib/constants.js'

function formatLatency(ms) {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} с` : `${ms} мс`
}

export default function SampleCard({ temperature, sample, run, busy, onRerun }) {
  const facts = run.text ? checkFacts(run.text, FACT_CHECKS) : []
  const meta = run.meta || {}
  const isTempZero = Number(temperature) === 0
  return (
    <article className={`sample${run.status === 'running' ? ' sample--running' : ''}`}>
      <div className="sample-head">
        <span className="mini-label">№{sample}</span>
        {run.seeded ? <span className="badge badge--seed">замороженный</span> : null}
      </div>
      {run.status === 'error' ? (
        <p className="errtext">{run.error}</p>
      ) : run.text ? (
        <div className="sample-text">{run.text}</div>
      ) : (
        <p className="answer-empty">
          {run.status === 'running' ? 'генерация…' : 'ещё не запущен'}
        </p>
      )}
      {facts.length > 0 ? (
        <div className="fact-row">
          {facts.map(f => (
            <span key={f.label} className={`badge ${f.ok ? 'badge--ok' : 'badge--no'}`}>
              {f.label} {f.ok ? '✓' : '✗'}
            </span>
          ))}
        </div>
      ) : null}
      <div className="sample-foot">
        <span className="meta">
          {meta.completion_tokens != null ? `${meta.completion_tokens} токенов` : '—'} ·{' '}
          {formatLatency(meta.latency_ms)}
          {meta.finish_reason ? ` · ${meta.finish_reason}` : ''}
        </span>
        <button
          type="button"
          className="chip-btn btn--sm"
          disabled={busy}
          onClick={() => onRerun(temperature, sample)}
        >
          перезапустить
        </button>
      </div>
    </article>
  )
}

export function Lane({ temperature, hint, items, busy, onRerun }) {
  const summary = laneSummary(items)
  const isTempZero = Number(temperature) === 0
  return (
    <section className="lane">
      <div className="lane-head">
        <div className="lane-title">
          <span className="temp-chip">temperature = {temperature}</span>
          <span className="lane-hint">{hint || TEMPERATURE_HINTS[Number(temperature)] || ''}</span>
        </div>
        {summary ? (
          <div className="lane-summary">
            {isTempZero ? (
              <span className={`badge ${summary.identical ? 'badge--ok' : 'badge--no'}`}>
                {summary.identical ? 't=0: прогоны идентичны' : 't=0: прогоны различаются!'}
              </span>
            ) : summary.identical ? (
              <span className="badge badge--ok">прогоны идентичны</span>
            ) : null}
            <span className="badge badge--unk">
              разнообразие: {diversityLabel(summary.similarity)}
            </span>
          </div>
        ) : null}
      </div>
      <div className="samples">
        {items.map((run, i) => (
          <SampleCard
            key={i}
            temperature={temperature}
            sample={i + 1}
            run={run}
            busy={busy}
            onRerun={onRerun}
          />
        ))}
      </div>
    </section>
  )
}
