import { useCallback, useRef, useState } from 'react'
import { useChat } from './hooks/useChat.js'
import { buildPayload, DEFAULT_SETTINGS, snapshot } from './lib/constants.js'
import TopBar from './components/TopBar.jsx'
import Chat from './components/Chat.jsx'
import Composer from './components/Composer.jsx'

let nextId = 1

export default function App() {
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const { chat, send, abort, reset } = useChat()
  const genRef = useRef(0)

  const handleSend = useCallback((text) => {
    const gen = ++genRef.current
    const userMsg = { id: nextId++, role: 'user', content: text, settings: snapshot(settings) }
    const history = [...messages, userMsg]
    setMessages(history)
    send(buildPayload(history, settings), (final) => {
      if (gen !== genRef.current) return
      setMessages(prev => [...prev, {
        id: nextId++,
        role: 'assistant',
        content: final.text,
        meta: final.meta,
        error: final.error,
        stopped: final.phase === 'stopped',
      }])
      reset()
    })
  }, [messages, settings, send, reset])

  const newChat = useCallback(() => {
    genRef.current++
    setMessages([])
    abort()
  }, [abort])

  return (
    <div className="app">
      <TopBar onNewChat={newChat} hasChat={messages.length > 0} />
      <Chat messages={messages} chat={chat} input={input} setInput={setInput} />
      <Composer
        settings={settings}
        setSettings={setSettings}
        busy={chat.phase === 'running'}
        onSend={handleSend}
        onStop={abort}
        input={input}
        setInput={setInput}
      />
    </div>
  )
}
