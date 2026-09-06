import { MODELS } from '../lib/constants.js'

export default function PromptCard({ prompt, onPromptChange, models, onToggleModel, job, inFlight, onStart, onStop }) {
  const busy = job != null
  const total = models.length

  return (
    <section className="task-card">
      <div className="task-head">
        <span className="side-title">Запрос</span>
        <div className="pick">
          {Object.entries(MODELS).map(([id, m]) => (
            <button
              key={id}
              type="button"
              className={`chip-btn${models.includes(id) ? ' chip-btn--on' : ''}`}
              disabled={busy}
              onClick={() => onToggleModel(id)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <textarea
        className="task-text"
        value={prompt}
        disabled={busy}
        placeholder="что спросить у моделей?"
        onChange={e => onPromptChange(e.target.value)}
      />
      <div className="runbar">
        {busy || inFlight ? (
          <>
            <button type="button" className="btn btn--stop" onClick={onStop}>
              остановить
            </button>
            {job ? (
              <span className="runline">
                <span className="dot" /> {job.done}/{job.total}
                {job.label ? ` · ${job.label}` : ''}
              </span>
            ) : (
              <span className="runline">
                <span className="dot" /> идёт прогон
              </span>
            )}
          </>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            disabled={total === 0 || !prompt.trim()}
            onClick={onStart}
          >
            запустить ({total})
          </button>
        )}
      </div>
    </section>
  )
}
