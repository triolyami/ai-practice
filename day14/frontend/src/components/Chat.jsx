import { useEffect, useRef } from 'react'
import { ENFORCE_LABEL, LAYER_SHORT, fmtMoney, fmtTokens } from '../lib/constants.js'

const EXAMPLES = [
  'Напиши сетевой слой Android-приложения на RxJava с Retrofit',
  'Почему RxJava считается хуже корутин для Android?',
  'Добавь в сервис доставку по Санкт-Петербургу',
  'Спроектируй экран профиля пользователя',
]

function checkLabel(kind) {
  return kind === 'ban_code' ? 'бан-код' : 'бан'
}

function MetaLine({ meta }) {
  const t = meta.tokens || {}
  const bits = [meta.model]
  if (meta.layers) {
    const on = Object.entries(meta.layers).filter(([, v]) => v).map(([k]) => LAYER_SHORT[k] || k)
    bits.push(`слои: ${on.length ? on.join('+') : '—'}`)
  }
  if (meta.invariant) bits.push(`инварианты «${meta.invariant}»`)
  if (meta.enforce) bits.push(`режим: ${ENFORCE_LABEL[meta.enforce] || meta.enforce}`)
  if (meta.attempts > 1) bits.push(`попыток: ${meta.attempts}`)
  if (meta.prompt_tokens != null) {
    bits.push(`промпт ${fmtTokens(meta.prompt_tokens)}`)
    bits.push(`ответ ${fmtTokens(meta.completion_tokens)}`)
  } else if (t.total_est != null) {
    bits.push(`≈${fmtTokens(t.total_est)} токенов (оценка)`)
  }
  if (t.est_error_pct != null) {
    bits.push(`ошибка оценки ${t.est_error_pct > 0 ? '+' : ''}${t.est_error_pct}%`)
  }
  if (t.invariants > 0) bits.push(`инварианты ≈${fmtTokens(t.invariants)}`)
  if (t.history != null) bits.push(`история ≈${fmtTokens(t.history)}`)
  if (t.context_used_pct != null) bits.push(`контекст ${t.context_used_pct}%`)
  if (meta.cost_usd != null) bits.push(fmtMoney(meta.cost_usd))
  if (meta.latency_ms != null) bits.push(`${(meta.latency_ms / 1000).toFixed(1)} с`)
  if (meta.finish_reason) bits.push(`finish=${meta.finish_reason}`)
  return (
    <div className="meta">
      <span>{bits.join(' · ')}</span>
      {meta.invariant_missing && (
        <span className="meta-warn">набор «{meta.invariant_id}» не найден — ответ без инвариантов</span>
      )}
      {meta.synthesized && (
        <span className="meta-warn">отказ синтезирован сервером после двух нарушений</span>
      )}
    </div>
  )
}

function Badges({ meta }) {
  if (!meta?.invariant_id) return null
  const violations = meta.violations || []
  const blocked = meta.blocked_attempts || []
  const verified = meta.enforce !== 'off' && !meta.refusal && !violations.length && !meta.synthesized
  return (
    <div className="badges">
      {meta.refusal && <span className="badge badge--refusal">отказ</span>}
      {violations.length > 0 && (
        <span className="badge badge--violation" title={violations.map(v => `${checkLabel(v.kind)}: ${v.pattern} → «${v.match}»`).join('\n')}>
          нарушение ×{violations.length}
        </span>
      )}
      {blocked.length > 0 && (
        <span className="badge badge--blocked">заблокировано ×{blocked.length}</span>
      )}
      {verified && <span className="badge badge--ok">проверено</span>}
      {meta.enforce === 'off' && <span className="badge badge--off">линтер выкл</span>}
    </div>
  )
}

function BlockedAttempt({ attempt, index, live }) {
  const viols = (attempt.violations || [])
    .map(v => `${checkLabel(v.kind)} «${v.pattern}»`)
    .join(', ')
  return (
    <details className="phase phase--blocked">
      <summary>
        попытка {index + 1} — заблокирована линтером{viols ? `: ${viols}` : ''}
        {live ? ' · ретрай…' : ''}
      </summary>
      <div className="phase-text">{attempt.content || 'пустой ответ'}</div>
    </details>
  )
}

function AssistantMessage({ m }) {
  const blocked = m.meta?.blocked_attempts || []
  return (
    <div className="msg msg--assistant">
      {m.error && <div className="errtext">{m.error}</div>}
      {blocked.length > 0 && (
        <div className="phases">
          {blocked.map((b, i) => <BlockedAttempt key={i} attempt={b} index={i} />)}
        </div>
      )}
      {!m.error && <Badges meta={m.meta} />}
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
  }, [messages, chat.text, chat.blocked, chat.phase, notice])

  const running = chat.phase === 'running'
  const blockedLive = chat.blocked || []

  return (
    <main className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="chat-col">
        {messages.length === 0 && !running && loading && (
          <p className="chat-loading">загружаю диалог…</p>
        )}

        {messages.length === 0 && !running && !loading && (
          <div className="welcome">
            <span className="pill">день 14 · инварианты</span>
            <h1>Агент, которому нельзя некоторые вещи</h1>
            <p className="lead">
              Набор инвариантов — markdown-файл с правилами проекта (стек,
              архитектура, бизнес-ограничения) и машинными проверками.
              Привяжите набор к чату в композере, и он уйдёт в каждый запрос
              отдельным блоком; а детерминированный линтер проверит ответ:
              «бан» сканирует весь текст, «бан-код» — только блоки кода.
              Режим «жёсткий» блокирует нарушение и повторяет запрос, при
              конфликте ассистент отвечает «ОТКАЗ: …» с альтернативой.
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
            {blockedLive.length > 0 && (
              <div className="phases">
                {blockedLive.map((b, i) => (
                  <BlockedAttempt key={i} attempt={b} index={i} live={i === blockedLive.length - 1} />
                ))}
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
