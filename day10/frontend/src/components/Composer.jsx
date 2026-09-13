import { useState } from 'react'
import SettingsPanel from './SettingsPanel.jsx'
import { STRATEGY_MODES } from '../lib/constants.js'
import { loadSettingsOpen, saveSettingsOpen } from '../lib/storage.js'

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
          <button
            type="button"
            className={`chip-btn${open ? ' chip-btn--on' : ''}`}
            onClick={toggleSettings}
            title={open ? 'Скрыть настройки агента' : 'Показать настройки агента'}
          >
            агент: {settings.name.trim() || 'Ассистент'} · {settings.model} ·{' '}
            {STRATEGY_MODES[settings.strategy] || 'окно'}
            {settings.strategy !== 'branches' && ` ${settings.windowSize}`}
            {' '}{open ? '▴' : '▾'}
          </button>
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
