import { MODELS } from '../lib/constants.js'

const SAMPLE_OPTIONS = [1, 2, 3, 4, 5]

export default function PromptCard({
  prompt,
  onPromptChange,
  model,
  onModelChange,
  samples,
  onSamplesChange,
  job,
  onStart,
  onStop,
}) {
  const total = MODELS[model].temperatures.length * samples
  const busy = job != null
  return (
    <section className="task-card">
      <div className="task-head">
        <span className="side-title">Запрос</span>
        <div className="pick">
          {Object.entries(MODELS).map(([id, m]) => (
            <button
              key={id}
              type="button"
              className={`chip-btn${model === id ? ' chip-btn--on' : ''}`}
              disabled={busy}
              onClick={() => onModelChange(id)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <p className="task-note">{MODELS[model].note}</p>
      <textarea
        className="task-text task-text--short"
        value={prompt}
        disabled={busy}
        onChange={e => onPromptChange(e.target.value)}
      />
      <p className="task-note">{MODELS[model].cap}</p>
      <div className="task-head">
        <div className="pick">
          <span className="mini-label">прогонов на температуру</span>
          {SAMPLE_OPTIONS.map(n => (
            <button
              key={n}
              type="button"
              className={`chip-btn${samples === n ? ' chip-btn--on' : ''}`}
              disabled={busy}
              onClick={() => onSamplesChange(n)}
            >
              {n}
            </button>
          ))}
        </div>
      </div>
      <div className="runbar">
        {busy ? (
          <>
            <button type="button" className="btn btn--stop" onClick={onStop}>
              остановить
            </button>
            <span className="runline">
              <span className="dot" /> {job.done}/{job.total}
              {job.label ? ` · ${job.label}` : ''}
            </span>
          </>
        ) : (
          <button type="button" className="btn btn--primary" onClick={onStart}>
            запустить ({total})
          </button>
        )}
      </div>
    </section>
  )
}
