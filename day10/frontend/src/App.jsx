import { useCallback, useEffect, useRef, useState } from 'react'
import { useChat } from './hooks/useChat.js'
import { snapshot } from './lib/constants.js'
import { MAX_CHATS, loadAgent, loadChats, saveAgent, saveChats } from './lib/storage.js'
import TopBar from './components/TopBar.jsx'
import ChatList from './components/ChatList.jsx'
import Chat from './components/Chat.jsx'
import TokenPanel from './components/TokenPanel.jsx'
import Composer from './components/Composer.jsx'
import ContextDiagram from './components/ContextDiagram.jsx'
import FactsPanel from './components/FactsPanel.jsx'

let nextId = 1

export default function App() {
  const [settings, setSettings] = useState(loadAgent)
  const [chats, setChats] = useState(loadChats)
  const [currentId, setCurrentId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [notice, setNotice] = useState(null)
  const [agentInfo, setAgentInfo] = useState(null)
  const { chat, send, abort, reset } = useChat()
  const genRef = useRef(0)
  const loadRef = useRef(0)

  useEffect(() => { saveChats(chats) }, [chats])
  useEffect(() => { saveAgent(settings) }, [settings])

  const patchChat = useCallback((id, patch) => {
    setChats(prev => prev.map(c => (c.id === id ? { ...c, ...patch } : c)))
  }, [])

  const newSessionId = () =>
    `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

  const loadTranscript = useCallback(async (id) => {
    const gen = ++loadRef.current
    try {
      const res = await fetch(`/api/agent?session_id=${encodeURIComponent(id)}`)
      const data = await res.json()
      if (gen !== loadRef.current) return
      if (!data.exists) {
        setMessages([])
        setAgentInfo(null)
        setNotice('Сервер не знает этот чат — агент будет пересоздан при первом сообщении (память агентов живёт до перезапуска сервера).')
        return
      }
      setMessages(data.messages.map((m, i) => ({ id: `${id}-${i}`, role: m.role, content: m.content, meta: m.meta })))
      setAgentInfo(data)
    } catch {
      if (gen === loadRef.current) setNotice('Не удалось загрузить память агента.')
    }
  }, [])

  const handleEvent = useCallback((ev) => {
    if (ev.event === 'done' && ev.meta) {
      setAgentInfo(prev => ({
        ...(prev || {}),
        totals: ev.meta.totals,
        context_preview: ev.meta.context_preview,
      }))
    } else if (ev.event === 'facts') {
      setAgentInfo(prev => ({
        ...(prev || {}),
        facts: ev.facts,
        context_preview: ev.context_preview,
        totals: ev.totals,
      }))
    } else if (ev.event === 'notice') {
      setNotice(ev.message)
    }
  }, [])

  const handleSend = useCallback((text) => {
    const gen = ++genRef.current
    let sid = currentId
    if (!sid) {
      sid = newSessionId()
      setCurrentId(sid)
      setChats(prev => [
        { id: sid, title: text.slice(0, 80), updatedAt: Date.now() },
        ...prev,
      ].slice(0, MAX_CHATS))
    }
    setMessages(prev => [...prev, { id: nextId++, role: 'user', content: text }])
    setNotice(null)

    send({ session_id: sid, message: text, config: snapshot(settings) }, (final) => {
      if (gen !== genRef.current) return
      const assistant = {
        id: nextId++,
        role: 'assistant',
        content: final.text,
        meta: final.meta,
        error: final.error,
        stopped: final.phase === 'stopped',
      }
      setMessages(prev => [...prev, assistant])
      patchChat(sid, { updatedAt: Date.now() })
      reset()
    }, handleEvent)
  }, [settings, currentId, send, reset, patchChat, handleEvent])

  const selectChat = useCallback((id) => {
    if (id === currentId) return
    genRef.current++
    abort()
    setCurrentId(id)
    setMessages([])
    setAgentInfo(null)
    setNotice(null)
    reset()
    loadTranscript(id)
  }, [currentId, abort, reset, loadTranscript])

  const forkChat = useCallback(async (count) => {
    if (!currentId) return
    try {
      const res = await fetch('/api/fork', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentId, count }),
      })
      const data = await res.json()
      if (!res.ok) {
        setNotice(data.error || 'Не удалось создать ветку.')
        return
      }
      genRef.current++
      abort()
      reset()
      const parentTitle = chats.find(c => c.id === currentId)?.title || 'чат'
      setChats(prev => [
        { id: data.session_id, title: `${parentTitle} · ветка`, branch: { at: count }, updatedAt: Date.now() },
        ...prev,
      ].slice(0, MAX_CHATS))
      setCurrentId(data.session_id)
      setMessages((data.messages || []).map((m, i) => ({ id: `${data.session_id}-${i}`, role: m.role, content: m.content, meta: m.meta })))
      setAgentInfo(data)
      setNotice(`Ветка создана с сообщения ${count}: дальше она живёт независимо, переключение — в списке слева.`)
    } catch {
      setNotice('Не удалось связаться с сервером.')
    }
  }, [currentId, chats, abort, reset])

  const newChat = useCallback(() => {
    genRef.current++
    abort()
    setCurrentId(null)
    setMessages([])
    setAgentInfo(null)
    setNotice(null)
    reset()
  }, [abort, reset])

  const deleteChat = useCallback((id) => {
    setChats(prev => prev.filter(c => c.id !== id))
    if (id === currentId) {
      genRef.current++
      abort()
      setCurrentId(null)
      setMessages([])
      setAgentInfo(null)
      setNotice(null)
    }
    fetch('/api/forget', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: id }),
    }).catch(() => {})
  }, [currentId, abort])

  const resetMemory = useCallback(async () => {
    if (!currentId) return
    try {
      const res = await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentId }),
      })
      if (res.ok) {
        const data = await res.json()
        setMessages([])
        setAgentInfo(prev => prev ? { ...prev, ...data } : data)
        setNotice('Память агента очищена: личность и настройки сохранены, диалог, факты и счётчики обнулены.')
      } else {
        setNotice('Не удалось сбросить память агента.')
      }
    } catch {
      setNotice('Не удалось связаться с сервером.')
    }
  }, [currentId])

  const tokenMetas = messages
    .filter(m => m.role === 'assistant' && m.meta?.tokens)
    .map(m => m.meta)
  const lastPct = tokenMetas.length ? tokenMetas[tokenMetas.length - 1].tokens.context_used_pct : 0
  const forkable = (agentInfo?.strategy ?? settings.strategy) === 'branches'
  const contextWarning =
    lastPct >= 80
      ? `Контекст заполнен на ${lastPct}% — следующий запрос может не влезть. Уменьшите окно или смените стратегию в настройках.`
      : null

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
          <TokenPanel
            metas={tokenMetas}
            model={settings.model}
            totals={agentInfo?.totals}
          />
          <Chat
            messages={messages}
            chat={chat}
            input={input}
            setInput={setInput}
            notice={notice}
            forkable={forkable}
            onFork={forkChat}
          />
          <Composer
            settings={settings}
            setSettings={setSettings}
            busy={chat.phase === 'running'}
            onSend={handleSend}
            onStop={abort}
            onReset={resetMemory}
            canReset={!!currentId}
            turns={Math.floor(messages.length / 2)}
            input={input}
            setInput={setInput}
            contextWarning={contextWarning}
          />
        </div>
        <aside className="rsidebar">
          <ContextDiagram
            preview={agentInfo?.context_preview}
            metas={tokenMetas}
          />
          <FactsPanel
            facts={agentInfo?.facts}
            strategy={settings.strategy}
          />
        </aside>
      </div>
    </div>
  )
}
