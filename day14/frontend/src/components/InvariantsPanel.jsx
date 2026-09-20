import { useState } from 'react'
import { INVARIANT_TEMPLATE } from '../lib/constants.js'
import { plural } from '../lib/format.js'

export default function InvariantsPanel({ invariants, boundId, onRefresh, onNotice }) {
  const [edit, setEdit] = useState(null) // {id, name, content, isNew}
  const [busy, setBusy] = useState('')

  const openInvariant = async (id) => {
    setBusy(`open:${id}`)
    try {
      const res = await fetch(`/api/invariant?id=${encodeURIComponent(id)}`)
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось прочитать набор инвариантов.')
        return
      }
      setEdit({ id: data.id, name: data.name, content: data.content, isNew: false })
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  const newInvariant = () =>
    setEdit({ id: null, name: '', content: INVARIANT_TEMPLATE, isNew: true })

  const save = async () => {
    setBusy('save')
    try {
      const body = edit.isNew
        ? { name: edit.name, content: edit.content }
        : { id: edit.id, content: edit.content }
      const res = await fetch('/api/invariant', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось сохранить набор инвариантов.')
        return
      }
      setEdit(null)
      onRefresh?.()
      onNotice?.(
        edit.isNew
          ? `Набор «${data.name}» сохранён как invariants/${data.id}.md — привяжите его к чату в композере.`
          : `Набор «${data.name}» сохранён — со следующего ответа чат увидит новую версию.`,
      )
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  const remove = async (id, name) => {
    if (!window.confirm(`Удалить набор «${name || id}»? Чаты, привязанные к нему, продолжат отвечать без инвариантов.`)) return
    setBusy(`del:${id}`)
    try {
      const res = await fetch('/api/invariant/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось удалить набор.')
        return
      }
      if (edit?.id === id) setEdit(null)
      onRefresh?.()
      onNotice?.(`Набор «${name || id}» удалён — привязанные чаты продолжат без инвариантов.`)
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  const checkCount = (inv) => (inv.checks || []).length
  const brokenCount = (inv) => (inv.checks || []).filter(c => c.broken).length

  return (
    <section className="ctx-panel">
      <div className="mem-sec-head">
        <span className="mini-label">инварианты</span>
        {!edit && (
          <button type="button" className="mem-btn" onClick={newInvariant}>
            + новый набор
          </button>
        )}
      </div>

      {!edit && (
        <>
          {(invariants || []).length === 0 ? (
            <p className="sum-empty">
              наборов нет — создайте свой из шаблона: это markdown-файл в day14/invariants/
            </p>
          ) : (
            <ul className="prof-list">
              {invariants.map(inv => (
                <li key={inv.id} className="prof-row">
                  <button
                    type="button"
                    className="prof-open"
                    disabled={busy === `open:${inv.id}`}
                    title={`invariants/${inv.id}.md`}
                    onClick={() => openInvariant(inv.id)}
                  >
                    <span className="prof-name">
                      {inv.name || inv.id}
                      {inv.id === boundId && <span className="prof-bound">привязан</span>}
                    </span>
                    <span className="prof-meta">
                      {Object.keys(inv.sections || {}).length}{' '}
                      {plural(Object.keys(inv.sections || {}).length, ['секция', 'секции', 'секций'])}
                      {' · '}{checkCount(inv)}{' '}
                      {plural(checkCount(inv), ['проверка', 'проверки', 'проверок'])}
                      {brokenCount(inv) > 0 && (
                        <span className="check-broken">
                          {' · '}{brokenCount(inv)} сломано
                        </span>
                      )}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="chatlist-del prof-del"
                    aria-label={`Удалить набор ${inv.name || inv.id}`}
                    disabled={busy === `del:${inv.id}`}
                    onClick={() => remove(inv.id, inv.name)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mem-note">
            файлы invariants/*.md · читаются с диска на каждый запрос — правка видна со следующего ответа
          </p>
        </>
      )}

      {edit && (
        <div className="mem-edit">
          {edit.isNew && (
            <>
              <label className="mini-label">имя набора — из него делается slug файла</label>
              <input
                type="text"
                className="input input--sm"
                value={edit.name}
                maxLength={120}
                placeholder="например: Бэкенд на FastAPI"
                onChange={e => setEdit(prev => ({ ...prev, name: e.target.value }))}
              />
            </>
          )}
          <label className="mini-label">
            {edit.isNew ? 'markdown набора' : `invariants/${edit.id}.md`}
          </label>
          <textarea
            className="input prompt-input mono"
            rows={12}
            value={edit.content}
            onChange={e => setEdit(prev => ({ ...prev, content: e.target.value }))}
          />
          <p className="mem-note">
            «## Секция» + строки «- ключ: значение» — правила для модели;
            «## Проверки» — линтер: «- бан: regex» сканирует весь ответ,
            «- бан-код: regex» — только блоки кода
          </p>
          <div className="mem-actions">
            <button
              type="button"
              className="mem-btn mem-btn--on"
              disabled={busy === 'save' || (edit.isNew && !edit.name.trim())}
              onClick={save}
            >
              сохранить
            </button>
            <button
              type="button"
              className="mem-btn"
              onClick={() => setEdit(prev => ({ ...prev, content: INVARIANT_TEMPLATE }))}
            >
              вставить шаблон
            </button>
            {!edit.isNew && (
              <button
                type="button"
                className="mem-btn"
                disabled={busy === `del:${edit.id}`}
                onClick={() => remove(edit.id, edit.name)}
              >
                удалить
              </button>
            )}
            <button type="button" className="mem-btn" onClick={() => setEdit(null)}>отмена</button>
          </div>
        </div>
      )}
    </section>
  )
}
