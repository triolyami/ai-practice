import { useEffect, useRef, useState } from 'react'
import SettingsPanel from './SettingsPanel.jsx'
import { LAYER_ORDER, LAYER_SHORT, profileLabel } from '../lib/constants.js'
import { loadSettingsOpen, saveSettingsOpen } from '../lib/storage.js'
import { plural } from '../lib/format.js'

const FILLER =
  'Это проверочный длинный текст: диалог с агентом растёт, и каждый новый запрос ' +
  'пересылает контекст целиком, поэтому промпт-токены накапливаются от хода к ходу. '
const FILLERS = [
  { label: '+10К', size: 10_000, title: 'Вставить ~10 000 символов — заметный рост токенов' },
  { label: '+50К', size: 50_000, title: 'Вставить ~50 000 символов — быстрый разогрев истории' },
]

function filler(size) {
  let s = ''
  while (s.length < size) s += FILLER
  return s.slice(0, size)
}

export default function Composer({
  settings, setSettings, profiles, busy, onSend, onStop, onReset, canReset, turns, input, setInput, contextWarning,
}) {
  const [open, setOpen] = useState(loadSettingsOpen)
  const [profOpen, setProfOpen] = useState(false)
  const profWrapRef = useRef(null)

  useEffect(() => {
    if (!profOpen) return
    const onDocClick = (e) => {
      if (profWrapRef.current && !profWrapRef.current.contains(e.target)) setProfOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [profOpen])

  const toggleSettings = () =>
    setOpen(prev => {
      saveSettingsOpen(!prev)
      return !prev
    })

  const pickProfile = (id) => {
    setSettings(prev => (prev.profile === id ? prev : { ...prev, profile: id }))
    setProfOpen(false)
  }

  const submit = () => {
    const text = input.trim()
    if (!text || busy) return
    onSend(text)
    setInput('')
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  const canSend = !busy && input.trim().length > 0
  const bound = settings.profile || ''
  const boundMissing = bound && !(profiles || []).some(p => p.id === bound)

  return (
    <div className="composer">
      <div className="composer-card">
        {open && (
          <SettingsPanel
            settings={settings}
            setSettings={setSettings}
            onReset={onReset}
            canReset={canReset}
            busy={busy}
            turns={turns}
          />
        )}
        {contextWarning && !open && <div className="ctx-warn">{contextWarning}</div>}
        <div className="composer-toolbar">
          <span className="composer-chips">
            <button
              type="button"
              className={`chip-btn${open ? ' chip-btn--on' : ''}`}
              onClick={toggleSettings}
              title={open ? 'Скрыть настройки агента' : 'Показать настройки агента'}
            >
              агент: {settings.name.trim() || 'Ассистент'} · {settings.model} ·{' '}
              {LAYER_ORDER.filter(k => settings.layers?.[k] !== false).map(k => LAYER_SHORT[k]).join('+') || 'слои выкл'}
              {' '}{open ? '▴' : '▾'}
            </button>
            <span className="chip-wrap" ref={profWrapRef}>
              <button
                type="button"
                className={`chip-btn${profOpen ? ' chip-btn--on' : ''}${boundMissing ? ' chip-btn--warn' : ''}`}
                onClick={() => setProfOpen(prev => !prev)}
                title="Профиль пользователя, привязанный к этому чату — уходит в каждый запрос отдельным блоком"
              >
                профиль: {bound ? profileLabel(profiles, bound) : 'нет'}
                {boundMissing ? ' · файл не найден' : ''}
                {' '}{profOpen ? '▴' : '▾'}
              </button>
              {profOpen && (
                <div className="prof-menu">
                  <button
                    type="button"
                    className={`prof-item${!bound ? ' prof-item--on' : ''}`}
                    onClick={() => pickProfile('')}
                  >
                    без профиля
                  </button>
                  {(profiles || []).map(p => (
                    <button
                      key={p.id}
                      type="button"
                      className={`prof-item${bound === p.id ? ' prof-item--on' : ''}`}
                      title={`profiles/${p.id}.md`}
                      onClick={() => pickProfile(p.id)}
                    >
                      {p.name || p.id}
                      {p.pipeline_steps?.length
                        ? ` · пайплайн ${p.pipeline_steps.length} ${plural(p.pipeline_steps.length, ['шаг', 'шага', 'шагов'])}`
                        : ''}
                    </button>
                  ))}
                  {boundMissing && (
                    <span className="prof-item prof-item--missing">
                      {bound} · файл не найден
                    </span>
                  )}
                  {(profiles || []).length === 0 && !boundMissing && (
                    <span className="prof-item prof-item--empty">профили создаются в панели справа</span>
                  )}
                </div>
              )}
            </span>
          </span>
          <span className="composer-hint">
            длинный текст:
            {FILLERS.map(f => (
              <button
                key={f.label}
                type="button"
                className="filler-btn"
                title={f.title}
                disabled={busy}
                onClick={() => setInput(prev => (prev ? prev + ' ' : '') + filler(f.size))}
              >
                {f.label}
              </button>
            ))}
          </span>
        </div>
        <div className="composer-row">
          <textarea
            className="composer-input"
            rows={1}
            placeholder="Напишите агенту…"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            type="button"
            className={`send${busy ? ' send--stop' : ''}`}
            disabled={!busy && !canSend}
            onClick={() => (busy ? onStop() : submit())}
            aria-label={busy ? 'Остановить' : 'Отправить'}
          >
            {busy ? '■' : '↑'}
          </button>
        </div>
      </div>
    </div>
  )
}
