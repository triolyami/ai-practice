import { useEffect, useRef } from 'react'

export default function Composer({ busy, onSend, onStop, input, setInput }) {
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

  const canSend = !busy && input.trim().length > 0

  return (
    <div className="composer">
      <div className="composer-card">
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
        <p className="composer-hint">Enter — отправить, Shift+Enter — перенос</p>
      </div>
    </div>
  )
}
