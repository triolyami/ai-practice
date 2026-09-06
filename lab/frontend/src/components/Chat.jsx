import { useEffect, useRef } from 'react'
import { plural } from '../lib/format.js'
import { describeSettings } from '../lib/constants.js'

const EXAMPLES = [
  'Расскажи, как устроен интернет',
  'Придумай пять названий для кофейни у метро',
  'Объясни школьнику, что такое рекурсия',
  'Напиши хайку про осень в Петербурге',
]

function prettyJson(text) {
  const trimmed = text.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2)
  } catch {
    return null
  }
}

function UserMessage({ m }) {
  const badges = describeSettings(m.settings)
  return (
    <div className="msg msg--user">
      {badges.length > 0 && (
        <div className="badges badges--user">
          {badges.map((b, i) => (
            <span key={i} className={`badge badge--${b.tone}`}>{b.text}</span>
          ))}
        </div>
      )}
      <div className="bubble-user">{m.content}</div>
    </div>
  )
}

function MetaLine({ meta, content }) {
  const bits = [meta.model]
  if (meta.finish_reason) bits.push(`finish=${meta.finish_reason}`)
  if (meta.completion_tokens != null) {
    bits.push(`${meta.completion_tokens} ${plural(meta.completion_tokens, ['токен', 'токена', 'токенов'])}`)
  }
  if (meta.metrics) {
    bits.push(`${meta.metrics.words} ${plural(meta.metrics.words, ['слово', 'слова', 'слов'])}`)
  }
  if (meta.latency_ms != null) bits.push(`${(meta.latency_ms / 1000).toFixed(1)} с`)
  const swallowed = !content && (meta.finish_reason === 'length' || meta.finish_reason === 'stop')
  const hasParams = meta.request && Object.keys(meta.request.params).length > 0
  return (
    <div className="meta">
      <span>{bits.join(' · ')}</span>
      {swallowed && <span className="meta-warn">пусто: токены ушли в скрытые рассуждения</span>}
      {meta.request && (
        <details className="request">
          <summary>что ушло в модель</summary>
          <pre className="out">{meta.request.content}</pre>
          {hasParams && <pre className="out">{JSON.stringify(meta.request.params, null, 2)}</pre>}
        </details>
      )}
    </div>
  )
}

function AssistantMessage({ m }) {
  const json = prettyJson(m.content || '')
  return (
    <div className="msg msg--assistant">
      {m.error && <div className="errtext">{m.error}</div>}
      {!m.error && json != null && <pre className="out out--answer">{json}</pre>}
      {!m.error && json == null && (
        <div className="answer">
          {m.content || <span className="answer-empty">пустой ответ</span>}
        </div>
      )}
      {m.stopped && <p className="stopnote">генерация остановлена вручную</p>}
      {m.meta && <MetaLine meta={m.meta} content={m.content} />}
    </div>
  )
}

export default function Chat({ messages, chat, input, setInput }) {
  const scrollRef = useRef(null)
  const stickRef = useRef(true)

  const onScroll = () => {
    const el = scrollRef.current
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages, chat.text, chat.phase])

  const running = chat.phase === 'running'

  return (
    <main className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="chat-col">
        {messages.length === 0 && !running && (
          <div className="welcome">
            <span className="pill">интерактивная лаборатория</span>
            <h1>Чат с ограничителями</h1>
            <p className="lead">
              Модель видит всю историю диалога и отвечает с учётом предыдущих
              сообщений. В панели слева включите формат, лимит длины или
              стоп-последовательность — инструкцией в промпте или параметром
              API; настройки применяются к конкретному сообщению.
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

        {messages.map(m =>
          m.role === 'user'
            ? <UserMessage key={m.id} m={m} />
            : <AssistantMessage key={m.id} m={m} />,
        )}

        {running && (
          <div className="msg msg--assistant">
            {chat.text
              ? <div className="answer">{chat.text}</div>
              : <div className="runline"><span className="dot" />модель генерирует ответ…</div>}
          </div>
        )}
      </div>
    </main>
  )
}
