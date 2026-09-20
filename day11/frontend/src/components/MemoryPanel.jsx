import { useCallback, useEffect, useState } from 'react'
import { plural } from '../lib/format.js'

function factsToText(facts) {
  return (facts || []).map(([k, v]) => `${k}: ${v}`).join('\n')
}

function textToFacts(text) {
  return text.split('\n')
    .map(l => l.trim())
    .filter(Boolean)
    .map(l => {
      const i = l.indexOf(':')
      return i > 0 ? [l.slice(0, i).trim(), l.slice(i + 1).trim()] : null
    })
    .filter(p => p && p[0] && p[1])
}

function textToPlan(text) {
  return text.split('\n').map(l => l.trim()).filter(Boolean)
}

export default function MemoryPanel({ info, sessionId, messageCount, onPatch, onNotice, pending, loading }) {
  const [lt, setLt] = useState(null)
  const [ltEdit, setLtEdit] = useState(null)
  const [wkEdit, setWkEdit] = useState(null)
  const [busy, setBusy] = useState('')

  const working = info?.working || null
  const covered = working?.covered ?? 0
  const msgCount = messageCount ?? info?.messages?.length ?? (info?.turns ?? 0) * 2
  const ltSig = `${info?.longterm?.chars ?? 0}:${info?.longterm?.items ?? 0}`

  const loadLongterm = useCallback(async () => {
    try {
      const res = await fetch('/api/longterm')
      if (res.ok) setLt(await res.json())
    } catch {}
  }, [])

  useEffect(() => { loadLongterm() }, [loadLongterm, ltSig])

  const saveLongterm = async () => {
    setBusy('lt')
    try {
      const res = await fetch('/api/longterm', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: ltEdit }),
      })
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось сохранить долговременную память.')
        return
      }
      setLt(data)
      setLtEdit(null)
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  const saveWorking = async () => {
    setBusy('wk')
    try {
      const res = await fetch('/api/working', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          goal: wkEdit.goal,
          plan: textToPlan(wkEdit.plan),
          facts: textToFacts(wkEdit.facts),
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось сохранить рабочую память.')
        return
      }
      onPatch?.({ working: data.working, workspace: data.workspace })
      setWkEdit(null)
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  const promote = async (key) => {
    setBusy(`p:${key}`)
    try {
      const res = await fetch('/api/promote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, key }),
      })
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось перенести факт.')
        return
      }
      onPatch?.({ working: data.working, workspace: data.workspace })
      loadLongterm()
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="ctx-panel">
      <span className="mini-label">слои памяти</span>

      <div className="mem-sec">
        <div className="mem-sec-head">
          <span className="mem-name">
            долговременная
            {pending && <span className="mem-pending"><span className="dot" />обновляю…</span>}
          </span>
          {lt && ltEdit === null && (
            <button type="button" className="mem-btn" onClick={() => setLtEdit(lt.content)}>
              изменить
            </button>
          )}
        </div>
        {lt === null ? (
          <p className="sum-empty">загружаю memory/longterm.md…</p>
        ) : ltEdit !== null ? (
          <div className="mem-edit">
            <textarea
              className="input prompt-input mono"
              rows={8}
              value={ltEdit}
              onChange={e => setLtEdit(e.target.value)}
            />
            <div className="mem-actions">
              <button type="button" className="mem-btn mem-btn--on" disabled={busy === 'lt'} onClick={saveLongterm}>
                сохранить
              </button>
              <button type="button" className="mem-btn" onClick={() => setLtEdit(null)}>отмена</button>
            </div>
          </div>
        ) : (
          <>
            {lt.content.trim() ? (
              <pre className="mem-file">{lt.content}</pre>
            ) : (
              <p className="sum-empty">файл memory/longterm.md пока пуст — записи появятся после ответов агента</p>
            )}
            <p className="mem-note">
              один файл на все чаты · переживает сброс, удаление чатов и перезапуск
            </p>
          </>
        )}
      </div>

      <div className="mem-sec">
        <div className="mem-sec-head">
          <span className="mem-name">
            рабочая{working?.workspace ? ` · ${working.workspace}` : ''}
            {pending && <span className="mem-pending"><span className="dot" />обновляю…</span>}
          </span>
          {working && wkEdit === null && (
            <button
              type="button"
              className="mem-btn"
              onClick={() => setWkEdit({
                goal: working.goal || '',
                plan: (working.plan || []).join('\n'),
                facts: factsToText(working.facts),
              })}
            >
              изменить
            </button>
          )}
        </div>
        {!info ? (
          <p className="sum-empty">
            {loading
              ? 'загружаю память агента…'
              : 'рабочая память появится после первого ответа — область задачи привяжется к чату'}
          </p>
        ) : wkEdit !== null ? (
          <div className="mem-edit">
            <label className="mini-label">цель</label>
            <input
              type="text"
              className="input input--sm"
              value={wkEdit.goal}
              onChange={e => setWkEdit(prev => ({ ...prev, goal: e.target.value }))}
            />
            <label className="mini-label">план — по шагу на строку</label>
            <textarea
              className="input prompt-input"
              rows={4}
              value={wkEdit.plan}
              onChange={e => setWkEdit(prev => ({ ...prev, plan: e.target.value }))}
            />
            <label className="mini-label">факты — «ключ: значение» на строку</label>
            <textarea
              className="input prompt-input mono"
              rows={5}
              value={wkEdit.facts}
              onChange={e => setWkEdit(prev => ({ ...prev, facts: e.target.value }))}
            />
            <div className="mem-actions">
              <button type="button" className="mem-btn mem-btn--on" disabled={busy === 'wk'} onClick={saveWorking}>
                сохранить
              </button>
              <button type="button" className="mem-btn" onClick={() => setWkEdit(null)}>отмена</button>
            </div>
          </div>
        ) : working && (working.goal || working.plan?.length || working.facts?.length) ? (
          <div className="mem-body">
            {working.goal && <p className="mem-goal">цель: {working.goal}</p>}
            {working.plan?.length > 0 && (
              <ol className="mem-plan">
                {working.plan.map((p, i) => <li key={i}>{p}</li>)}
              </ol>
            )}
            {working.facts?.length > 0 && (
              <dl className="facts-list">
                {working.facts.map(([key, value]) => (
                  <div key={key} className="facts-row facts-row--btn">
                    <dt>
                      {key}
                      <button
                        type="button"
                        className="mem-btn mem-btn--promote"
                        disabled={busy === `p:${key}`}
                        title="Перенести факт в долговременную память (memory/longterm.md → Знания)"
                        onClick={() => promote(key)}
                      >
                        → в долговременную
                      </button>
                    </dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="mem-note">
              область «{working.workspace || 'личная'}» · учтено {covered}{' '}
              {plural(covered, ['сообщение', 'сообщения', 'сообщений'])} · общая для всех чатов области
            </p>
          </div>
        ) : (
          <p className="sum-empty">
            пусто — после каждого ответа модель складывает сюда цель, план и факты задачи
          </p>
        )}
      </div>

      <div className="mem-sec">
        <span className="mem-name">краткосрочная</span>
        <p className="mem-note">
          {msgCount} {plural(msgCount, ['сообщение', 'сообщения', 'сообщений'])} текущего диалога —
          уходит в запрос целиком, живёт только в этом чате
        </p>
      </div>
    </section>
  )
}
