import { useState } from 'react'
import { PROFILE_TEMPLATE } from '../lib/constants.js'
import { plural } from '../lib/format.js'

export default function ProfilesPanel({ profiles, boundId, onRefresh, onNotice }) {
  const [edit, setEdit] = useState(null) // {id, name, content, isNew}
  const [busy, setBusy] = useState('')

  const openProfile = async (id) => {
    setBusy(`open:${id}`)
    try {
      const res = await fetch(`/api/profile?id=${encodeURIComponent(id)}`)
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось прочитать профиль.')
        return
      }
      setEdit({ id: data.id, name: data.name, content: data.content, isNew: false })
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  const newProfile = () =>
    setEdit({ id: null, name: '', content: PROFILE_TEMPLATE, isNew: true })

  const save = async () => {
    setBusy('save')
    try {
      const body = edit.isNew
        ? { name: edit.name, content: edit.content }
        : { id: edit.id, content: edit.content }
      const res = await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось сохранить профиль.')
        return
      }
      setEdit(null)
      onRefresh?.()
      onNotice?.(
        edit.isNew
          ? `Профиль «${data.name}» сохранён как profiles/${data.id}.md — привяжите его к чату в композере.`
          : `Профиль «${data.name}» сохранён — со следующего ответа чат увидит новую версию.`,
      )
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  const remove = async (id, name) => {
    if (!window.confirm(`Удалить профиль «${name || id}»? Чаты, привязанные к нему, продолжат отвечать без профиля.`)) return
    setBusy(`del:${id}`)
    try {
      const res = await fetch('/api/profile/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      const data = await res.json()
      if (!res.ok) {
        onNotice?.(data.error || 'Не удалось удалить профиль.')
        return
      }
      if (edit?.id === id) setEdit(null)
      onRefresh?.()
      onNotice?.(`Профиль «${name || id}» удалён — привязанные чаты продолжат без профиля.`)
    } catch {
      onNotice?.('Не удалось связаться с сервером.')
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="ctx-panel">
      <div className="mem-sec-head">
        <span className="mini-label">профили</span>
        {!edit && (
          <button type="button" className="mem-btn" onClick={newProfile}>
            + новый профиль
          </button>
        )}
      </div>

      {!edit && (
        <>
          {(profiles || []).length === 0 ? (
            <p className="sum-empty">
              профилей нет — создайте свой из шаблона: это markdown-файл в day12/profiles/
            </p>
          ) : (
            <ul className="prof-list">
              {profiles.map(p => (
                <li key={p.id} className="prof-row">
                  <button
                    type="button"
                    className="prof-open"
                    disabled={busy === `open:${p.id}`}
                    title={`profiles/${p.id}.md`}
                    onClick={() => openProfile(p.id)}
                  >
                    <span className="prof-name">
                      {p.name || p.id}
                      {p.id === boundId && <span className="prof-bound">привязан</span>}
                    </span>
                    <span className="prof-meta">
                      {Object.keys(p.sections || {}).length}{' '}
                      {plural(Object.keys(p.sections || {}).length, ['секция', 'секции', 'секций'])}
                      {p.pipeline_steps?.length
                        ? ` · пайплайн ${p.pipeline_steps.length} ${plural(p.pipeline_steps.length, ['шаг', 'шага', 'шагов'])}`
                        : ''}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="chatlist-del prof-del"
                    aria-label={`Удалить профиль ${p.name || p.id}`}
                    disabled={busy === `del:${p.id}`}
                    onClick={() => remove(p.id, p.name)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mem-note">
            файлы profiles/*.md · читаются с диска на каждый запрос — правка видна со следующего ответа
          </p>
        </>
      )}

      {edit && (
        <div className="mem-edit">
          {edit.isNew && (
            <>
              <label className="mini-label">имя профиля — из него делается slug файла</label>
              <input
                type="text"
                className="input input--sm"
                value={edit.name}
                maxLength={120}
                placeholder="например: Код-ревьюер"
                onChange={e => setEdit(prev => ({ ...prev, name: e.target.value }))}
              />
            </>
          )}
          <label className="mini-label">
            {edit.isNew ? 'markdown профиля' : `profiles/${edit.id}.md`}
          </label>
          <textarea
            className="input prompt-input mono"
            rows={12}
            value={edit.content}
            onChange={e => setEdit(prev => ({ ...prev, content: e.target.value }))}
          />
          <p className="mem-note">
            «## Секция» + строки «- ключ: значение» — предпочтения; «## Пайплайн» — шаги,
            которые выполнятся по очереди отдельными запросами
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
              onClick={() => setEdit(prev => ({ ...prev, content: PROFILE_TEMPLATE }))}
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
