import { useEffect, useRef, useState } from 'react'
import SettingsPanel from './SettingsPanel.jsx'
import { LAYER_ORDER, LAYER_SHORT, PROBES, invariantLabel } from '../lib/constants.js'
import { loadSettingsOpen, saveSettingsOpen } from '../lib/storage.js'
import { plural } from '../lib/format.js'

export default function Composer({
  settings, setSettings, invariants, busy, onSend, onStop, onReset, canReset, turns, input, setInput, contextWarning,
}) {
  const [open, setOpen] = useState(loadSettingsOpen)
  const [invOpen, setInvOpen] = useState(false)
  const invWrapRef = useRef(null)

  useEffect(() => {
    if (!invOpen) return
    const onDocClick = (e) => {
      if (invWrapRef.current && !invWrapRef.current.contains(e.target)) setInvOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [invOpen])

  const toggleSettings = () =>
    setOpen(prev => {
      saveSettingsOpen(!prev)
      return !prev
    })

  const pickInvariant = (id) => {
    setSettings(prev => (prev.invariant === id ? prev : { ...prev, invariant: id }))
    setInvOpen(false)
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
  const bound = settings.invariant || ''
  const boundMissing = bound && !(invariants || []).some(i => i.id === bound)

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
            <span className="chip-wrap" ref={invWrapRef}>
              <button
                type="button"
                className={`chip-btn${invOpen ? ' chip-btn--on' : ''}${boundMissing ? ' chip-btn--warn' : ''}`}
                onClick={() => setInvOpen(prev => !prev)}
                title="Набор инвариантов, привязанный к этому чату — уходит в каждый запрос отдельным блоком"
              >
                инварианты: {bound ? invariantLabel(invariants, bound) : 'нет'}
                {boundMissing ? ' · файл не найден' : ''}
                {' '}{invOpen ? '▴' : '▾'}
              </button>
              {invOpen && (
                <div className="prof-menu">
                  <button
                    type="button"
                    className={`prof-item${!bound ? ' prof-item--on' : ''}`}
                    onClick={() => pickInvariant('')}
                  >
                    без инвариантов
                  </button>
                  {(invariants || []).map(inv => (
                    <button
                      key={inv.id}
                      type="button"
                      className={`prof-item${bound === inv.id ? ' prof-item--on' : ''}`}
                      title={`invariants/${inv.id}.md`}
                      onClick={() => pickInvariant(inv.id)}
                    >
                      {inv.name || inv.id}
                      {(inv.checks || []).length
                        ? ` · ${inv.checks.length} ${plural(inv.checks.length, ['проверка', 'проверки', 'проверок'])}`
                        : ''}
                    </button>
                  ))}
                  {boundMissing && (
                    <span className="prof-item prof-item--missing">
                      {bound} · файл не найден
                    </span>
                  )}
                  {(invariants || []).length === 0 && !boundMissing && (
                    <span className="prof-item prof-item--empty">наборы создаются в панели справа</span>
                  )}
                </div>
              )}
            </span>
          </span>
          <span className="composer-hint">
            пробы:
            {PROBES.map(p => (
              <button
                key={p.label}
                type="button"
                className="filler-btn"
                title={p.hint}
                disabled={busy}
                onClick={() => setInput(p.text)}
              >
                {p.label}
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
