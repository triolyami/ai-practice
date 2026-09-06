import { useCallback, useEffect, useRef, useState } from 'react'
import { useChat } from './hooks/useChat.js'
import { buildPayload, snapshot } from './lib/constants.js'
import { MAX_CHATS, loadChats, loadSettings, saveChats, saveSettings } from './lib/storage.js'
import TopBar from './components/TopBar.jsx'
import ChatList from './components/ChatList.jsx'
import Chat from './components/Chat.jsx'
import Composer from './components/Composer.jsx'

let nextId = 1

function bootChats() {
  const chats = loadChats()
  chats.forEach(c => c.messages.forEach(m => { m.id = nextId++ }))
  return chats
}

export default function App() {
  const [settings, setSettings] = useState(loadSettings)
  const [chats, setChats] = useState(bootChats)
  const [currentId, setCurrentId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const { chat, send, abort, reset } = useChat()
  const genRef = useRef(0)

  useEffect(() => { saveChats(chats) }, [chats])
  useEffect(() => { saveSettings(settings) }, [settings])

  const patchChat = useCallback((id, patch) => {
    setChats(prev => prev.map(c => (c.id === id ? { ...c, ...patch } : c)))
  }, [])

  const handleSend = useCallback((text) => {
    const gen = ++genRef.current
    const userMsg = { id: nextId++, role: 'user', content: text, settings: snapshot(settings) }
    const history = [...messages, userMsg]
    setMessages(history)

    let convId = currentId
    if (!convId) {
      convId = `c-${Date.now().toString(36)}-${nextId}`
      setCurrentId(convId)
      setChats(prev => [
        { id: convId, title: text.slice(0, 80), createdAt: Date.now(), updatedAt: Date.now(), messages: history },
        ...prev,
      ].slice(0, MAX_CHATS))
    } else {
      patchChat(convId, { messages: history, updatedAt: Date.now() })
    }

    send(buildPayload(history, settings), (final) => {
      if (gen !== genRef.current) return
      const assistant = {
        id: nextId++,
        role: 'assistant',
        content: final.text,
        meta: final.meta,
        error: final.error,
        stopped: final.phase === 'stopped',
      }
      const next = [...history, assistant]
      setMessages(next)
      patchChat(convId, { messages: next, updatedAt: Date.now() })
      reset()
    })
  }, [messages, settings, currentId, send, reset, patchChat])

  const selectChat = useCallback((id) => {
    if (id === currentId) return
    genRef.current++
    abort()
    const conv = chats.find(c => c.id === id)
    if (!conv) return
    setCurrentId(id)
    setMessages(conv.messages.map(m => ({ ...m })))
    reset()
  }, [chats, currentId, abort, reset])

  const newChat = useCallback(() => {
    genRef.current++
    abort()
    setCurrentId(null)
    setMessages([])
    reset()
  }, [abort, reset])

  const deleteChat = useCallback((id) => {
    setChats(prev => prev.filter(c => c.id !== id))
    if (id === currentId) {
      genRef.current++
      abort()
      setCurrentId(null)
      setMessages([])
    }
  }, [currentId, abort])

  return (
    <div className="app">
      <TopBar />
      <div className="layout">
        <aside className="sidebar">
          <ChatList
            chats={chats}
            currentId={currentId}
            onSelect={selectChat}
            onNew={newChat}
            onDelete={deleteChat}
          />
        </aside>
        <div className="main">
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
      </div>
    </div>
  )
}
