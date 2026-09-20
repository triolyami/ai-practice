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

let nextId = 1

export default function App() {
  const [settings, setSettings] = useState(loadAgent)
  const [chats, setChats] = useState(loadChats)
  const [workspaces, setWorkspaces] = useState([])
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

  const loadWorkspaces = useCallback(async () => {
    try {
      const res = await fetch('/api/workspaces')
      if (res.ok) {
        const data = await res.json()
        setWorkspaces(data.workspaces || [])
      }
    } catch {}
  }, [])

  useEffect(() => { loadWorkspaces() }, [loadWorkspaces])

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
      const ws = data.workspace || ''
      patchChat(id, { workspace: ws })
      setSettings(prev => (prev.workspace === ws ? prev : { ...prev, workspace: ws }))
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
        workspace: ev.meta.workspace,
        layers: ev.meta.layers,
        totals: ev.meta.totals,
        context_preview: ev.meta.context_preview,
      }))
    } else if (ev.event === 'memory') {
      setMemPending(false)
      setAgentInfo(prev => ({
        ...(prev || {}),
        workspace: ev.workspace,
        workspace_id: ev.workspace_id,
        working: ev.working,
        context_preview: ev.context_preview,
        totals: ev.totals,
      }))
      loadWorkspaces()
    } else if (ev.event === 'notice') {
      setMemPending(false)
      setNotice(ev.message)
    }
  }, [patchChat, loadWorkspaces])

  const handleSend = useCallback((text) => {
    const gen = ++genRef.current
    let sid = currentId
    if (!sid) {
      sid = newSessionId()
      setCurrentId(sid)
      setChats(prev => [
        { id: sid, title: text.slice(0, 80), updatedAt: Date.now(), workspace: settings.workspace || '' },
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
      }
      setMessages(prev => [...prev, assistant])
      const ws = final.meta?.workspace
      patchChat(sid, { updatedAt: Date.now(), ...(ws !== undefined ? { workspace: ws || '' } : {}) })
      loadWorkspaces()
      reset()
    }, handleEvent)
  }, [settings, currentId, send, reset, patchChat, handleEvent, loadWorkspaces])

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
    const ws = chats.find(c => c.id === id)?.workspace || ''
    setSettings(prev => (prev.workspace === ws ? prev : { ...prev, workspace: ws }))
    loadTranscript(id, { background: !!cached })
  }, [currentId, chats, abort, reset, loadTranscript])

  const newChat = useCallback((workspace = '') => {
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
    setSettings(prev => (prev.workspace === workspace ? prev : { ...prev, workspace }))
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

  const deleteWorkspace = useCallback(async (wsid, name) => {
    if (!window.confirm(`Удалить область «${name}»? Рабочая память сотрётся, чаты вернутся к личной.`)) return
    try {
      const res = await fetch('/api/workspace/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsid }),
      })
      const data = await res.json()
      if (!res.ok) {
        setNotice(data.error || 'Не удалось удалить область.')
        return
      }
      setChats(prev => prev.map(c => (c.workspace === name ? { ...c, workspace: '' } : c)))
      if (currentId && (data.reverted || []).includes(currentId)) {
        setSettings(prev => ({ ...prev, workspace: '' }))
        setAgentInfo(prev => (prev ? { ...prev, workspace: '', workspace_id: currentId } : prev))
      }
      loadWorkspaces()
      setNotice(`Область «${name}» удалена — её рабочая память очищена.`)
    } catch {
      setNotice('Не удалось связаться с сервером.')
    }
  }, [currentId, loadWorkspaces])

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
        setNotice('Краткосрочная память очищена: диалог и счётчики обнулены. Рабочая область и долговременная память не затронуты.')
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
            workspaces={workspaces}
            currentId={currentId}
            onSelect={selectChat}
            onNew={newChat}
            onDelete={deleteChat}
            onDeleteWorkspace={deleteWorkspace}
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
            workspaces={workspaces}
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
