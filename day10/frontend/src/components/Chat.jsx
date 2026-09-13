import { useEffect, useRef } from 'react'
import { plural } from '../lib/format.js'
import { fmtMoney, fmtTokens } from '../lib/constants.js'

const EXAMPLES = [
  'Привет! Расскажи, что ты умеешь',
  'Запомни: мой любимый цвет — синий. Что мой любимый цвет?',
  'Мы собираем ТЗ для сайта кофейни. Цель — запустить через месяц',
  'Расскажи длинную историю про кота и чемодан',
]

function MetaLine({ meta }) {
  const t = meta.tokens || {}
  const bits = [meta.model]
  if (meta.strategy_label) bits.push(meta.strategy_label)
  if (meta.prompt_tokens != null) {
    bits.push(`промпт ${fmtTokens(meta.prompt_tokens)}`)
    bits.push(`ответ ${fmtTokens(meta.completion_tokens)}`)
  } else if (t.total_est != null) {
    bits.push(`≈${fmtTokens(t.total_est)} токенов (оценка)`)
  }
  if (t.est_error_pct != null) {
    bits.push(`ошибка оценки ${t.est_error_pct > 0 ? '+' : ''}${t.est_error_pct}%`)
  }
  if (t.extra > 0) bits.push(`факты ≈${fmtTokens(t.extra)}`)
  if (t.history != null) bits.push(`история ≈${fmtTokens(t.history)}`)
  if (meta.outside > 0) {
    const word = plural(meta.outside, ['сообщение', 'сообщения', 'сообщений'])
    bits.push(meta.strategy === 'facts'
      ? `факты покрывают ${meta.outside} ${word}`
      : `за окном ${meta.outside} ${word}`)
  }
  if (t.context_used_pct != null) bits.push(`контекст ${t.context_used_pct}%`)
  if (meta.cost_usd != null) bits.push(fmtMoney(meta.cost_usd))
  if (meta.latency_ms != null) bits.push(`${(meta.latency_ms / 1000).toFixed(1)} с`)
  if (meta.finish_reason) bits.push(`finish=${meta.finish_reason}`)
  return (
    <div className="meta">
      <span>{bits.join(' · ')}</span>
    </div>
  )
}

function AssistantMessage({ m }) {
  return (
    <div className="msg msg--assistant">
      {m.error && <div className="errtext">{m.error}</div>}
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

function ForkButton({ count, onFork, running }) {
  return (
    <button
      type="button"
      className="fork-btn"
      disabled={running}
      title={`Создать ветку с сохранением первых ${count} сообщений — продолжение пойдёт независимо`}
      onClick={() => onFork(count)}
    >
      ⤵ ветка отсюда
    </button>
  )
}

export default function Chat({ messages, chat, input, setInput, notice, forkable, onFork }) {
  const scrollRef = useRef(null)
  const stickRef = useRef(true)

  const onScroll = () => {
    const el = scrollRef.current
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages, chat.text, chat.phase, notice])

  const running = chat.phase === 'running'

  return (
    <main className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="chat-col">
        {messages.length === 0 && !running && (
          <div className="welcome">
            <span className="pill">день 10 · стратегии контекста</span>
            <h1>Чат с тремя способами управлять контекстом</h1>
            <p className="lead">
              «Окно» — в модель уходят только последние N сообщений, остальное
              отбрасывается. «Факты» — агент держит блок «ключ: значение» (цель,
              ограничения, решения) и шлёт его вместе с последними сообщениями,
              обновляя после каждого хода. «Ветки» — история не режется: чекпойнт
              ставится кнопкой «⤵ ветка отсюда», и от одного места можно развести
              два независимых продолжения. Карта контекста справа и панель токенов
              показывают цену каждого варианта.
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

        {messages.map((m, i) => (
          <div key={m.id} className={`msg-wrap${forkable ? ' msg-wrap--forkable' : ''}`}>
            {m.role === 'user'
              ? <div className="msg msg--user"><div className="bubble-user">{m.content}</div></div>
              : <AssistantMessage m={m} />}
            {forkable && <ForkButton count={i + 1} onFork={onFork} running={running} />}
          </div>
        ))}

        {running && (
          <div className="msg msg--assistant">
            {chat.text
              ? <div className="answer">{chat.text}</div>
              : <div className="runline"><span className="dot" />агент думает…</div>}
          </div>
        )}
      </div>
    </main>
  )
}
