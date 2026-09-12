import { useEffect, useRef } from 'react'
import { plural } from '../lib/format.js'

const EXAMPLES = [
  'Привет! Расскажи, что ты умеешь',
  'Запомни: мой любимый цвет — синий. Что мой любимый цвет?',
  'Объясни школьнику, что такое рекурсия',
  'Напиши хайку про осень в Петербурге',
]

function MetaLine({ meta }) {
  const bits = [meta.agent || 'агент', meta.model]
  if (meta.finish_reason) bits.push(`finish=${meta.finish_reason}`)
  if (meta.completion_tokens != null) {
    bits.push(`${meta.completion_tokens} ${plural(meta.completion_tokens, ['токен', 'токена', 'токенов'])}`)
  }
  if (meta.turns != null) {
    bits.push(`${meta.turns} ${plural(meta.turns, ['реплика', 'реплики', 'реплик'])} в памяти`)
  }
  if (meta.latency_ms != null) bits.push(`${(meta.latency_ms / 1000).toFixed(1)} с`)
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
            <span className="pill">день 6 · первый агент</span>
            <h1>Чат с агентом</h1>
            <p className="lead">
              Агент — отдельная сущность на сервере: он сам хранит историю
              диалога, сам собирает промпт из личности и памяти и сам ходит
              в LLM через API. Интерфейсу остаётся только пересылать ваш текст.
              Каждый чат слева — отдельный экземпляр агента со своей памятью.
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
