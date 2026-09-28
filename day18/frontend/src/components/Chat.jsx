import { useEffect, useRef } from 'react'
import { LAYER_SHORT, fmtMoney, fmtTokens } from '../lib/constants.js'
import { formatStamp } from '../lib/format.js'

const EXAMPLES = [
  'Напомни через 2 минуты проверить сборку',
  'Что собралось? Покажи сводку за 10 минут',
  'Какие задачи сейчас открыты в трекере?',
  'Создай задачу «Проверить MCP-вызов» с высоким приоритетом',
]

function argsPreview(args) {
  if (args == null) return ''
  const s = typeof args === 'object' ? JSON.stringify(args) : String(args)
  return s.length > 80 ? `${s.slice(0, 80)}…` : s
}

function ToolCallPhase({ call }) {
  const status = call.ok == null ? 'вызов…' : call.ok ? 'ok' : 'ошибка'
  const ms = call.latency_ms != null ? ` · ${call.latency_ms} мс` : ''
  return (
    <details className={`phase${call.ok === false ? ' phase--blocked' : ''}`}>
      <summary>
        {call.name} {argsPreview(call.arguments)} — {status}{ms}
      </summary>
      <div className="phase-text">
        {call.arguments != null && `аргументы: ${JSON.stringify(call.arguments)}\n\n`}
        {call.preview ?? 'жду результат…'}
      </div>
    </details>
  )
}

function MetaLine({ meta }) {
  if (meta.kind === 'scheduler') {
    // сообщение вотчера: без токенов и модели — просто пометка и время события
    const when = meta.ts ? formatStamp(meta.ts * 1000) : null
    return (
      <div className="meta">
        <span>{when ? `планировщик · ${when}` : 'планировщик'}</span>
      </div>
    )
  }
  const t = meta.tokens || {}
  const bits = [meta.model]
  if (meta.layers) {
    const on = Object.entries(meta.layers).filter(([, v]) => v).map(([k]) => LAYER_SHORT[k] || k)
    bits.push(`слои: ${on.length ? on.join('+') : '—'}`)
  }
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
  if (t.context_used_pct != null) bits.push(`контекст ${t.context_used_pct}%`)
  if (meta.tool_calls?.length) bits.push(`инструментов: ${meta.tool_calls.length}`)
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
  const calls = m.meta?.tool_calls || []
  return (
    <div className="msg msg--assistant">
      {calls.length > 0 && (
        <div className="phases">
          {calls.map((c, i) => <ToolCallPhase key={i} call={c} />)}
        </div>
      )}
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
  }, [messages, chat.text, chat.phase, chat.toolCalls, notice])

  const running = chat.phase === 'running'
  const liveCalls = chat.toolCalls || []

  return (
    <main className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="chat-col">
        {messages.length === 0 && !running && loading && (
          <p className="chat-loading">загружаю диалог…</p>
        )}

        {messages.length === 0 && !running && !loading && (
          <div className="welcome">
            <span className="pill">день 18 · планировщик и фоновые задачи</span>
            <h1>Агент, который работает сам</h1>
            <p className="lead">
              База дня 17 — чат с тулколлингом — теперь с четвёртым
              MCP-сервером: планировщиком. Он хранит задачи в SQLite и
              исполняет их по расписанию: разовые напоминания и
              интервальный сборщик метрик трекера. Сработавшие задачи
              складываются в очередь событий, которую вотчер в server.py
              разбирает каждые 15 секунд и превращает в сообщения чата
              «сводка» — он закреплён вверху списка и помечается бейджем,
              когда приходит новое. Тот же агрегат доступен инструментом
              summary по запросу.
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
            {liveCalls.length > 0 && (
              <div className="phases">
                {liveCalls.map((c, i) => <ToolCallPhase key={i} call={c} />)}
              </div>
            )}
            {chat.text
              ? <div className="answer">{chat.text}</div>
              : <div className="runline"><span className="dot" />агент думает…</div>}
          </div>
        )}
      </div>
    </main>
  )
}
