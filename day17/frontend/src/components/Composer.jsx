import { useState } from 'react'
import SettingsPanel from './SettingsPanel.jsx'
import { LAYER_ORDER, LAYER_SHORT } from '../lib/constants.js'
import { loadSettingsOpen, saveSettingsOpen } from '../lib/storage.js'

export default function Composer({
  settings, setSettings, busy, onSend, onStop, onReset, canReset, turns, input, setInput, contextWarning,
}) {
  const [open, setOpen] = useState(loadSettingsOpen)

  const toggleSettings = () =>
    setOpen(prev => {
      saveSettingsOpen(!prev)
      return !prev
    })

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
          </span>
          <span className="composer-hint">
            MCP-инструменты — в панели справа
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
