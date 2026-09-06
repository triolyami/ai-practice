import { verdictFor } from '../lib/answer.js'
import { plural } from '../lib/format.js'

function MetaLine({ meta, phases }) {
  const bits = [meta.model]
  if (meta.steps > 1) bits.push(`${meta.steps} ${plural(meta.steps, ['шаг', 'шага', 'шагов'])}`)
  if (meta.finish_reason) bits.push(`finish=${meta.finish_reason}`)
  if (meta.completion_tokens != null) {
    bits.push(`${meta.completion_tokens} ${plural(meta.completion_tokens, ['токен', 'токена', 'токенов'])}`)
  }
  if (meta.latency_ms != null) bits.push(`${(meta.latency_ms / 1000).toFixed(1)} с`)
  const lastReq = phases[phases.length - 1]?.request
  return (
    <div className="meta">
      <span>{bits.join(' · ')}</span>
      {lastReq && (
        <details className="request">
          <summary>что ушло в модель</summary>
          <pre className="out">{lastReq.content}</pre>
        </details>
      )}
    </div>
  )
}

const VERDICT_BADGES = {
  true: { cls: 'badge--ok', text: 'совпало с эталоном' },
  false: { cls: 'badge--no', text: 'не совпало' },
  null: { cls: 'badge--unk', text: 'ответ не распознан' },
}

export default function AgentCard({ agent, state, onRun, busy, builtIn }) {
  const s = state || { status: 'idle' }
  const phases = s.phases || []
  const mainPhase = phases[phases.length - 1]
  const running = s.status === 'running'
  const text = running ? mainPhase?.content || '' : s.text
  const verdict = verdictFor(s, builtIn)

  return (
    <article id={`strat-${agent.id}`} className={`strat-card${running ? ' strat-card--running' : ''}`}>
      <div className="strat-head">
        <div className="strat-head-text">
          <h3 className="strat-title">{agent.name || 'без названия'}</h3>
          <p className="strat-hint">{agent.instruction || 'пусто — просто задача'}</p>
        </div>
        <span className={`strat-model${agent.model === 'glm-5.3' ? ' strat-model--warn' : ''}`}>
          {agent.model}
        </span>
      </div>

      <div className="strat-body">
        {s.status === 'idle' && <p className="strat-empty">ещё не запускался</p>}
        {s.error && <div className="errtext">{s.error}</div>}
        {!s.error && s.status !== 'idle' && (
          <div className="answer">
            {text || (running ? (
              <span className="runline">
                <span className="dot" />модель думает…
              </span>
            ) : (
              <span className="answer-empty">пустой ответ</span>
            ))}
          </div>
        )}
        {s.stopped && <p className="stopnote">генерация остановлена вручную</p>}
        {s.meta && <MetaLine meta={s.meta} phases={phases} />}
      </div>

      <div className="strat-foot">
        {s.status !== 'idle' && (
          <button className="chip-btn" onClick={onRun} disabled={busy}>
            перезапустить
          </button>
        )}
        {builtIn && s.status === 'done' && (
          <span className={`badge ${VERDICT_BADGES[String(verdict)]?.cls || 'badge--unk'}`}>
            {(VERDICT_BADGES[String(verdict)] || VERDICT_BADGES.null).text}
          </span>
        )}
      </div>
    </article>
  )
}
