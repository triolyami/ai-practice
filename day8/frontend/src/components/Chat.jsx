import { useEffect, useRef } from 'react'
import { plural } from '../lib/format.js'
import { fmtMoney, fmtTokens } from '../lib/constants.js'

const EXAMPLES = [
  'Привет! Расскажи, что ты умеешь',
  'Запомни: мой любимый цвет — синий. Что мой любимый цвет?',
  'Объясни школьнику, что такое рекурсия',
  'Напиши хайку про осень в Петербурге',
]

function MetaLine({ meta }) {
  const t = meta.tokens || {}
  const bits = [meta.model]
  if (meta.prompt_tokens != null) {
    bits.push(`промпт ${fmtTokens(meta.prompt_tokens)}`)
    bits.push(`ответ ${fmtTokens(meta.completion_tokens)}`)
  } else if (t.total_est != null) {
    bits.push(`≈${fmtTokens(t.total_est)} токенов (оценка)`)
  }
  if (t.est_error_pct != null) {
    bits.push(`ошибка оценки ${t.est_error_pct > 0 ? '+' : ''}${t.est_error_pct}%`)
  }
  if (t.history != null) bits.push(`история ≈${fmtTokens(t.history)}`)
  if (t.request != null) bits.push(`запрос ≈${fmtTokens(t.request)}`)
  if (t.context_used_pct != null) bits.push(`контекст ${t.context_used_pct}%`)
  if (meta.cost_usd != null) bits.push(fmtMoney(meta.cost_usd))
  if (meta.turns != null) {
    bits.push(`${meta.turns} ${plural(meta.turns, ['реплика', 'реплики', 'реплик'])} в памяти`)
  }
  if (meta.latency_ms != null) bits.push(`${(meta.latency_ms / 1000).toFixed(1)} с`)
  if (meta.finish_reason) bits.push(`finish=${meta.finish_reason}`)
  return (
    <div className="meta">
      <span>{bits.join(' · ')}</span>
    </div>
  )
}

function AssistantMessage({ m }) {
  const trimmed = m.meta?.tokens?.trimmed_turns ?? 0
  return (
    <div className="msg msg--assistant">
      {m.error && <div className="errtext">{m.error}</div>}
      {!m.error && (
        <div className="answer">
          {m.content || <span className="answer-empty">пустой ответ</span>}
        </div>
      )}
      {trimmed > 0 && (
        <p className="trimnote">
          агент забыл {trimmed} {plural(trimmed, ['реплику', 'реплики', 'реплик'])} — они не влезли в контекст
        </p>
      )}
      {m.stopped && <p className="stopnote">генерация остановлена вручную</p>}
      {m.meta && <MetaLine meta={m.meta} />}
    </div>
  )
}

export default function Chat({ messages, chat, input, setInput, notice }) {
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
            <span className="pill">день 8 · токены</span>
            <h1>Чат с агентом и счётчиком токенов</h1>
            <p className="lead">
              Тот же агент, что и в дне 6, но теперь он считает токены: панель над чатом
              показывает оценку контекста до отправки, точные числа от API после ответа,
              накопленную стоимость и рост промпта от хода к ходу. Если диалог не влезает
              в контекст модели — агент покажет ошибку или, в режиме «обрезать историю»,
              забудет самые старые реплики и продолжит разговор.
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

        {messages.map(m =>
          m.role === 'user'
            ? <div key={m.id} className="msg msg--user"><div className="bubble-user">{m.content}</div></div>
            : <AssistantMessage key={m.id} m={m} />,
        )}

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
