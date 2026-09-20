import { useEffect, useRef } from 'react'
import { LAYER_SHORT, fmtMoney, fmtTokens } from '../lib/constants.js'

const EXAMPLES = [
  'Запомни: меня зовут Толик и я люблю короткие ответы',
  'Придумай название для кофейни у метро',
  'Что ты знаешь обо мне и моих предпочтениях?',
  'Разбери идею: телеграм-бот для записи к парикмахеру',
]

function MetaLine({ meta }) {
  const t = meta.tokens || {}
  const bits = [meta.model]
  if (meta.layers) {
    const on = Object.entries(meta.layers).filter(([, v]) => v).map(([k]) => LAYER_SHORT[k] || k)
    bits.push(`слои: ${on.length ? on.join('+') : '—'}`)
  }
  if (meta.profile) bits.push(`профиль «${meta.profile}»`)
  if (meta.pipeline?.length) bits.push(`пайплайн: ${meta.pipeline.join(' → ')}`)
  if (meta.prompt_tokens != null) {
    bits.push(`промпт ${fmtTokens(meta.prompt_tokens)}`)
    bits.push(`ответ ${fmtTokens(meta.completion_tokens)}`)
  } else if (t.total_est != null) {
    bits.push(`≈${fmtTokens(t.total_est)} токенов (оценка)`)
  }
  if (t.est_error_pct != null) {
    bits.push(`ошибка оценки ${t.est_error_pct > 0 ? '+' : ''}${t.est_error_pct}%`)
  }
  if (t.longterm > 0) bits.push(`долг. ≈${fmtTokens(t.longterm)}`)
  if (t.profile > 0) bits.push(`проф. ≈${fmtTokens(t.profile)}`)
  if (t.history != null) bits.push(`история ≈${fmtTokens(t.history)}`)
  if (t.context_used_pct != null) bits.push(`контекст ${t.context_used_pct}%`)
  if (meta.cost_usd != null) bits.push(fmtMoney(meta.cost_usd))
  if (meta.latency_ms != null) bits.push(`${(meta.latency_ms / 1000).toFixed(1)} с`)
  if (meta.finish_reason) bits.push(`finish=${meta.finish_reason}`)
  return (
    <div className="meta">
      <span>{bits.join(' · ')}</span>
      {meta.profile_missing && (
        <span className="meta-warn">профиль «{meta.profile_id}» не найден — ответ без профиля</span>
      )}
    </div>
  )
}

function StepPhase({ step, live }) {
  const toks = step.completion_tokens != null ? ` · ${fmtTokens(step.completion_tokens)} ток.` : ''
  return (
    <details className="phase" open={live && !step.done}>
      <summary>
        {step.name}
        {step.done ? toks : live ? ' · выполняется…' : ' · ждёт'}
      </summary>
      <div className="phase-text">
        {step.text || (live ? '…' : 'вывод шага не хранится в истории')}
      </div>
    </details>
  )
}

function AssistantMessage({ m }) {
  const steps = m.steps?.length
    ? m.steps
    : (m.meta?.pipeline || []).map(name => ({ name, text: '', done: true }))
  const phases = steps.slice(0, -1) // вывод последнего шага — это и есть ответ ниже
  return (
    <div className="msg msg--assistant">
      {m.error && <div className="errtext">{m.error}</div>}
      {phases.length > 0 && (
        <div className="phases">
          {phases.map((s, i) => <StepPhase key={i} step={s} live={false} />)}
        </div>
      )}
      {!m.error && (
        <div className="answer">
          {m.content || <span className="answer-empty">пустой ответ</span>}
        </div>
      )}
      {m.stopped && <p className="stopnote">генерация остановлена вручную</p>}
      {m.meta && <MetaLine meta={m.meta} />}
    </div>
  )
}

export default function Chat({ messages, chat, input, setInput, notice, loading }) {
  const scrollRef = useRef(null)
  const stickRef = useRef(true)

  const onScroll = () => {
    const el = scrollRef.current
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages, chat.text, chat.steps, chat.phase, notice])

  const running = chat.phase === 'running'
  const steps = chat.steps || []
  const lastStep = steps.length ? steps[steps.length - 1] : null
  const liveText = lastStep ? lastStep.text : chat.text

  return (
    <main className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="chat-col">
        {messages.length === 0 && !running && loading && (
          <p className="chat-loading">загружаю диалог…</p>
        )}

        {messages.length === 0 && !running && !loading && (
          <div className="welcome">
            <span className="pill">день 12 · персонализация</span>
            <h1>Агент, который знает, с кем говорит</h1>
            <p className="lead">
              Профиль пользователя — markdown-файл со своими предпочтениями
              (стиль, формат, ограничения): привяжите его к чату в композере,
              и он уйдёт в каждый запрос отдельным блоком. Секция «## Пайплайн»
              превращает ответ в цепочку шагов — каждый шаг виден как фаза.
              Поверх этого работает память: краткосрочная (весь диалог) и
              долговременная (memory/longterm.md) — выученное не дублирует
              заявленное в профиле.
            </p>
            <div className="examples">
              {EXAMPLES.map(ex => (
                <button key={ex} type="button" className="example" onClick={() => setInput(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {notice && <div className="notice">{notice}</div>}

        {messages.map(m => (
          <div key={m.id} className="msg-wrap">
            {m.role === 'user'
              ? <div className="msg msg--user"><div className="bubble-user">{m.content}</div></div>
              : <AssistantMessage m={m} />}
          </div>
        ))}

        {running && (
          <div className="msg msg--assistant">
            {steps.length > 1 && (
              <div className="phases">
                {steps.slice(0, -1).map((s, i) => <StepPhase key={i} step={s} live />)}
              </div>
            )}
            {liveText
              ? <div className="answer">{liveText}</div>
              : <div className="runline"><span className="dot" />агент думает…</div>}
          </div>
        )}
      </div>
    </main>
  )
}
