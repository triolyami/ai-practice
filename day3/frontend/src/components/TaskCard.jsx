import { DEFAULT_TASK } from '../lib/constants.js'

export default function TaskCard({ task, setTask, busy, onRun, onStop, onReset, hasRuns, agents, selected, onToggle }) {
  const custom = task.trim() !== DEFAULT_TASK.trim()
  const count = selected.length
  return (
    <section className="task-card">
      <div className="task-head">
        <span className="side-title">что запускать</span>
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
      <div className="pick">
        {agents.map(a => (
          <button
            key={a.id}
            className={`chip-btn pick-chip${selected.includes(a.id) ? ' chip-btn--on' : ''}`}
            onClick={() => onToggle(a.id)}
            disabled={busy}
            title={a.instruction || 'пусто — просто задача'}
          >
            {a.name || 'без названия'}
          </button>
        ))}
      </div>
      <div className="task-head">
        <span className="side-title">задача</span>
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
        <button className="btn btn--primary" onClick={onRun} disabled={busy || count === 0}>
          {count === 0 ? 'выберите агента' : `запустить (${count})`}
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
