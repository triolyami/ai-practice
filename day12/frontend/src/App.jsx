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
import MemoryPanel from './components/MemoryPanel.jsx'
import ProfilesPanel from './components/ProfilesPanel.jsx'

let nextId = 1

export default function App() {
  const [settings, setSettings] = useState(loadAgent)
  const [chats, setChats] = useState(loadChats)
  const [profiles, setProfiles] = useState([])
  const [currentId, setCurrentId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [notice, setNotice] = useState(null)
  const [agentInfo, setAgentInfo] = useState(null)
  const [loadingChat, setLoadingChat] = useState(false)
  const [memPending, setMemPending] = useState(false)
  const { chat, send, abort, reset } = useChat()
  const genRef = useRef(0)
  const loadRef = useRef(0)
  const transcriptCache = useRef(new Map())

  useEffect(() => { saveChats(chats) }, [chats])
  useEffect(() => { saveAgent(settings) }, [settings])

  useEffect(() => {
    if (!currentId || loadingChat) return
    transcriptCache.current.set(currentId, { messages, info: agentInfo })
  }, [messages, agentInfo, currentId, loadingChat])

  const patchChat = useCallback((id, patch) => {
    setChats(prev => prev.map(c => (c.id === id ? { ...c, ...patch } : c)))
  }, [])

  const patchInfo = useCallback((patch) => {
    setAgentInfo(prev => (prev ? { ...prev, ...patch } : patch))
  }, [])

  const loadProfiles = useCallback(async () => {
    try {
      const res = await fetch('/api/profiles')
      if (res.ok) {
        const data = await res.json()
        setProfiles(data.profiles || [])
      }
    } catch {}
  }, [])

  useEffect(() => { loadProfiles() }, [loadProfiles])

  // привязка профиля из композера: обновляет настройки и бейдж текущего чата
  useEffect(() => {
    if (currentId) patchChat(currentId, { profile: settings.profile || '' })
  }, [settings.profile, currentId, patchChat])

  const newSessionId = () =>
    `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

  const loadTranscript = useCallback(async (id, { background = false } = {}) => {
    const gen = ++loadRef.current
    if (!background) setLoadingChat(true)
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
      const pid = data.profile_id || ''
      patchChat(id, { profile: pid })
      setSettings(prev => (prev.profile === pid ? prev : { ...prev, profile: pid }))
    } catch {
      if (gen === loadRef.current) setNotice('Не удалось загрузить память агента.')
    } finally {
      if (gen === loadRef.current) setLoadingChat(false)
    }
  }, [patchChat])

  const handleEvent = useCallback((ev) => {
    if (ev.event === 'done' && ev.meta) {
      setMemPending(true)
      setAgentInfo(prev => ({
        ...(prev || {}),
        layers: ev.meta.layers,
        profile_id: ev.meta.profile_id,
        profile: ev.meta.profile,
        profile_missing: ev.meta.profile_missing,
        pipeline: ev.meta.pipeline,
        totals: ev.meta.totals,
        context_preview: ev.meta.context_preview,
      }))
    } else if (ev.event === 'memory') {
      setMemPending(false)
      setAgentInfo(prev => ({
        ...(prev || {}),
        covered: ev.covered,
        context_preview: ev.context_preview,
        totals: ev.totals,
      }))
    } else if (ev.event === 'notice') {
      setMemPending(false)
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
        { id: sid, title: text.slice(0, 80), updatedAt: Date.now(), profile: settings.profile || '' },
        ...prev,
      ].slice(0, MAX_CHATS))
    }
    setMessages(prev => [...prev, { id: nextId++, role: 'user', content: text }])
    setNotice(null)

    send({ session_id: sid, message: text, config: snapshot(settings) }, (final) => {
      if (gen !== genRef.current) return
      setMemPending(false)
      const assistant = {
        id: nextId++,
        role: 'assistant',
        content: final.text,
        meta: final.meta,
        error: final.error,
        stopped: final.phase === 'stopped',
        steps: final.steps,
      }
      setMessages(prev => [...prev, assistant])
      const pid = final.meta?.profile_id
      patchChat(sid, { updatedAt: Date.now(), ...(pid !== undefined ? { profile: pid || '' } : {}) })
      reset()
    }, handleEvent)
  }, [settings, currentId, send, reset, patchChat, handleEvent])

  const selectChat = useCallback((id) => {
    if (id === currentId) return
    genRef.current++
    abort()
    setCurrentId(id)
    const cached = transcriptCache.current.get(id)
    setMessages(cached?.messages || [])
    setAgentInfo(cached?.info || null)
    setNotice(null)
    setMemPending(false)
    reset()
    const pid = chats.find(c => c.id === id)?.profile || ''
    setSettings(prev => (prev.profile === pid ? prev : { ...prev, profile: pid }))
    loadTranscript(id, { background: !!cached })
  }, [currentId, chats, abort, reset, loadTranscript])

  const newChat = useCallback(() => {
    genRef.current++
    loadRef.current++
    abort()
    setLoadingChat(false)
    setCurrentId(null)
    setMessages([])
    setAgentInfo(null)
    setNotice(null)
    setMemPending(false)
    reset()
  }, [abort, reset])

  const deleteChat = useCallback((id) => {
    transcriptCache.current.delete(id)
    setChats(prev => prev.filter(c => c.id !== id))
    if (id === currentId) {
      genRef.current++
      loadRef.current++
      abort()
      setLoadingChat(false)
      setCurrentId(null)
      setMessages([])
      setAgentInfo(null)
      setNotice(null)
      setMemPending(false)
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
        setNotice('Краткосрочная память очищена: диалог и счётчики обнулены. Профили и долговременная память не затронуты.')
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
  const contextWarning =
    lastPct >= 80
      ? `Контекст заполнен на ${lastPct}% — следующий запрос может не влезть. Выключите часть слоёв в настройках или начните новый чат.`
      : null

  return (
    <div className="app">
      <TopBar />
      <div className="layout">
        <aside className="sidebar">
          <ChatList
            chats={chats}
            profiles={profiles}
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
            preview={agentInfo?.context_preview}
          />
          <Chat
            messages={messages}
            chat={chat}
            input={input}
            setInput={setInput}
            notice={notice}
            loading={loadingChat}
          />
          <Composer
            settings={settings}
            setSettings={setSettings}
            profiles={profiles}
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
          <ProfilesPanel
            profiles={profiles}
            boundId={settings.profile || ''}
            onRefresh={loadProfiles}
            onNotice={setNotice}
          />
          <MemoryPanel
            info={agentInfo}
            sessionId={currentId}
            messageCount={messages.length}
            onPatch={patchInfo}
            onNotice={setNotice}
            pending={memPending}
            loading={loadingChat}
          />
        </aside>
      </div>
    </div>
  )
}
