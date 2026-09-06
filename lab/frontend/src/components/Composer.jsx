import { useEffect, useRef, useState } from 'react'
import { activeControlNames } from '../lib/constants.js'
import SettingsPanel from './SettingsPanel.jsx'

export default function Composer({ settings, setSettings, busy, onSend, onStop, input, setInput }) {
  const [open, setOpen] = useState(false)
  const taRef = useRef(null)

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 220) + 'px'
  }, [input])

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

  const active = activeControlNames(settings)
  const canSend = !busy && input.trim().length > 0

  return (
    <div className="composer">
      <div className="composer-card">
        {open && <SettingsPanel settings={settings} setSettings={setSettings} />}
        <div className="composer-toolbar">
          <button
            type="button"
            className={`chip-btn${open ? ' chip-btn--on' : ''}`}
            onClick={() => setOpen(o => !o)}
          >
            настройки{active.length > 0 ? ` · ${active.join(', ')}` : ''}
          </button>
          <span className="composer-hint">Enter — отправить, Shift+Enter — перенос</span>
        </div>
        <div className="composer-row">
          <textarea
            ref={taRef}
            className="composer-input"
            rows={1}
            placeholder="Спросите что угодно…"
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
