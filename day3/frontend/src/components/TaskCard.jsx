import { DEFAULT_TASK } from '../lib/constants.js'

export default function TaskCard({ task, setTask, busy, onRunMain, onRunExtra, onStop, onReset, hasRuns }) {
  const custom = task.trim() !== DEFAULT_TASK.trim()
  return (
    <section className="task-card">
      <div className="task-head">
        <span className="side-title">задача</span>
        <div className="task-actions">
          {custom && (
            <button className="chip-btn" onClick={() => setTask(DEFAULT_TASK)} disabled={busy}>
              вернуть встроенную
            </button>
          )}
          {hasRuns && (
            <button className="chip-btn" onClick={onReset} disabled={busy}>
              начать заново
            </button>
          )}
        </div>
      </div>
      <textarea
        className="task-text"
        value={task}
        onChange={e => setTask(e.target.value)}
        disabled={busy}
        rows={10}
      />
      <div className="task-note">
        у встроенной задачи единственный ответ — это проверено перебором всех
        комбинаций в day3/verify.py; свою задачу тоже можно вписать, но тогда
        автоматическая сверка с эталоном недоступна
      </div>
      <div className="runbar">
        <button className="btn btn--primary" onClick={onRunMain} disabled={busy}>
          запустить 4 способа
        </button>
        <button className="btn" onClick={onRunExtra} disabled={busy}>
          + доп. эксперименты
        </button>
        {busy && (
          <button className="btn btn--stop" onClick={onStop}>
            стоп
          </button>
        )}
      </div>
    </section>
  )
}
