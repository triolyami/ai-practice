import { useCallback, useEffect, useState } from 'react'
import { plural } from '../lib/format.js'

export default function MemoryPanel({ info, sessionId, messageCount, onPatch, onNotice, pending, loading }) {
  const [lt, setLt] = useState(null)
  const [ltEdit, setLtEdit] = useState(null)
  const [busy, setBusy] = useState('')

  const covered = info?.covered ?? 0
  const msgCount = messageCount ?? info?.messages?.length ?? (info?.turns ?? 0) * 2
  const ltSig = `${info?.longterm?.chars ?? 0}:${info?.longterm?.items ?? 0}`

  const loadLongterm = useCallback(async () => {
    try {
      const res = await fetch('/api/longterm')
      if (res.ok) setLt(await res.json())
    } catch {}
  }, [])

  useEffect(() => { loadLongterm() }, [loadLongterm, ltSig, pending])

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
              один файл на все чаты · учтено {covered}{' '}
              {plural(covered, ['сообщение', 'сообщения', 'сообщений'])} этого диалога ·
              заявленное в профиле сюда не дублируется
            </p>
          </>
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
