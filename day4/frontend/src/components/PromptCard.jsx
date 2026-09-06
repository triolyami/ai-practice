import {
  EFFORTS,
  MAX_TEMPERATURE_POINTS,
  MIN_TEMPERATURE_POINTS,
  MODELS,
  NEW_TEMPERATURE,
  laneTemperatures,
  parseTemp,
} from '../lib/constants.js'

const SAMPLE_OPTIONS = [1, 2, 3, 4, 5]

export default function PromptCard({
  prompt,
  onPromptChange,
  model,
  onModelChange,
  samples,
  onSamplesChange,
  effort,
  onEffortChange,
  temps,
  onTempsChange,
  job,
  onStart,
  onStop,
}) {
  const total = laneTemperatures(temps).length * samples
  const busy = job != null
  const hasInvalid = temps.some(raw => parseTemp(raw) == null)
  const overOne = MODELS[model].thinking === 'off' && laneTemperatures(temps).some(t => t > 1)

  const setTemp = (i, value) => onTempsChange(temps.map((raw, j) => (j === i ? value : raw)))
  const addTemp = () => onTempsChange([...temps, NEW_TEMPERATURE])
  const removeTemp = i => onTempsChange(temps.filter((_, j) => j !== i))

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
      {MODELS[model].thinking === 'effort' && (
        <div className="pick">
          <span className="mini-label">effort</span>
          {EFFORTS.map(e => (
            <button
              key={e}
              type="button"
              className={`chip-btn${effort === e ? ' chip-btn--on' : ''}`}
              disabled={busy}
              onClick={() => onEffortChange(e)}
            >
              {e}
            </button>
          ))}
        </div>
      )}
      <div className="pick">
        <span className="mini-label">температуры</span>
        {temps.map((raw, i) => (
          <span key={i} className="temp-slot">
            <input
              type="text"
              inputMode="decimal"
              className={`temp-input${parseTemp(raw) == null ? ' temp-input--bad' : ''}`}
              value={raw}
              disabled={busy}
              onChange={e => setTemp(i, e.target.value)}
            />
            <button
              type="button"
              className="chip-btn btn--sm temp-remove"
              disabled={busy || temps.length <= MIN_TEMPERATURE_POINTS}
              onClick={() => removeTemp(i)}
              aria-label="убрать температуру"
            >
              ×
            </button>
          </span>
        ))}
        <button
          type="button"
          className="chip-btn btn--sm"
          disabled={busy || temps.length >= MAX_TEMPERATURE_POINTS}
          onClick={addTemp}
        >
          + точка
        </button>
      </div>
      {hasInvalid && <p className="task-note task-note--warn">температуры — числа от 0 до 2</p>}
      {overOne && (
        <p className="task-note task-note--warn">
          glm-4.6 принимает только 0–1 — прогоны выше 1 отклонит API (ошибка 1210)
        </p>
      )}
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
          <button
            type="button"
            className="btn btn--primary"
            disabled={total === 0}
            onClick={onStart}
          >
            запустить ({total})
          </button>
        )}
      </div>
    </section>
  )
}
