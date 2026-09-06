import { useCallback, useEffect, useRef, useState } from 'react'
import { useRuns } from './hooks/useRuns.js'
import { useAgents } from './hooks/useAgents.js'
import { DEFAULT_AGENTS, DEFAULT_TASK } from './lib/constants.js'
import { clearState, loadState, saveState } from './lib/storage.js'
import TopBar from './components/TopBar.jsx'
import TaskCard from './components/TaskCard.jsx'
import AgentCard from './components/AgentCard.jsx'
import AgentSidebar from './components/AgentSidebar.jsx'
import Compare from './components/Compare.jsx'

export default function App() {
  const { agents, setAgents } = useAgents()
  const [task, setTask] = useState(DEFAULT_TASK)
  const [frozenAt, setFrozenAt] = useState(null)
  const [selected, setSelected] = useState(() => agents.map(a => a.id))
  const { runs, replaceAll, run, abort, drop } = useRuns()
  const stopRef = useRef(false)
  const persistRef = useRef('')

  useEffect(() => {
    const ids = new Set(agents.map(a => a.id))
    const saved = loadState()
    if (saved) {
      setTask(saved.task)
      replaceAll(saved.runs)
      return
    }
    fetch('/results.json')
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (!data || !Array.isArray(data.runs)) return
        const restored = {}
        for (const r of data.runs) {
          if (!ids.has(r.id)) continue
          restored[r.id] = {
            status: 'done',
            text: r.content,
            phases: r.phases || [],
            meta: r.meta,
            error: null,
            stopped: false,
            frozen: true,
            verdict: r.verdict ?? null,
          }
        }
        setTask(data.meta?.task || DEFAULT_TASK)
        replaceAll(restored)
        setFrozenAt(data.meta?.generated_at || null)
      })
      .catch(() => {})
  }, [replaceAll])

  useEffect(() => {
    const terminal = {}
    for (const [id, r] of Object.entries(runs)) {
      if (r.status === 'done' || r.status === 'error') {
        terminal[id] = {
          status: r.status,
          text: r.text,
          phases: r.phases,
          meta: r.meta,
          error: r.error,
        }
      }
    }
    const json = JSON.stringify({ task, runs: terminal })
    if (json === persistRef.current) return
    persistRef.current = json
    saveState({ task, runs: terminal })
  }, [runs, task])

  const busy = Object.values(runs).some(r => r.status === 'running')
  const hasLocal = Object.values(runs).some(
    r => !r.frozen && (r.status === 'done' || r.status === 'error'),
  )
  const hasRuns = Object.keys(runs).length > 0

  const toggleSel = useCallback(id => {
    setSelected(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]))
  }, [])

  const runMany = useCallback(
    async list => {
      stopRef.current = false
      for (const agent of list) {
        if (stopRef.current) break
        await run(agent, task)
      }
    },
    [run, task],
  )

  const runSelected = useCallback(() => {
    const list = agents.filter(a => selected.includes(a.id))
    if (!list.length) return
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document.getElementById(`strat-${list[0].id}`)?.scrollIntoView({ block: 'start' })
      })
    })
    runMany(list)
  }, [agents, runMany, selected])

  const stopAll = useCallback(() => {
    stopRef.current = true
    abort()
  }, [abort])

  const startOwn = useCallback(() => {
    stopRef.current = true
    abort()
    clearState()
    persistRef.current = ''
    replaceAll({})
    setTask(DEFAULT_TASK)
    setFrozenAt(null)
    setSelected(agents.map(a => a.id))
  }, [abort, replaceAll, agents])

  const createAgent = useCallback(
    agent => {
      setAgents(prev => [...prev, agent])
      setSelected(prev => [...prev, agent.id])
    },
    [setAgents],
  )

  const saveAgent = useCallback(
    (id, draft) => {
      setAgents(prev => prev.map(a => (a.id === id ? { ...a, ...draft } : a)))
    },
    [setAgents],
  )

  const deleteAgent = useCallback(
    id => {
      setAgents(prev => prev.filter(a => a.id !== id))
      setSelected(prev => prev.filter(x => x !== id))
      drop(id)
    },
    [drop, setAgents],
  )

  const resetAgents = useCallback(() => {
    const fresh = DEFAULT_AGENTS.map(a => ({ ...a }))
    const ids = new Set(fresh.map(a => a.id))
    setAgents(fresh)
    setSelected(fresh.map(a => a.id))
    replaceAll(Object.fromEntries(Object.entries(runs).filter(([id]) => ids.has(id))))
  }, [replaceAll, runs, setAgents])

  const frozenStamp = frozenAt
    ? new Date(frozenAt).toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : null

  const builtIn = task.trim() === DEFAULT_TASK.trim()
  const visible = agents.filter(a => selected.includes(a.id))

  return (
    <div className="app">
      <TopBar />
      <div className="layout">
        <AgentSidebar
          agents={agents}
          busy={busy}
          onCreate={createAgent}
          onSave={saveAgent}
          onDelete={deleteAgent}
          onReset={resetAgents}
        />
        <main className="page-scroll">
          <div className="col">
            <header className="hero">
              <span className="pill">день 3 · разные способы рассуждения</span>
              <h1>Четыре способа решить одну задачу</h1>
              <p className="lead">
                Одна логическая задача решается через API агентами: у каждого —
                своя инструкция и модель, запуск — один запрос. Четыре агента
                встроены по заданию: прямой ответ, пошаговое решение, группа
                экспертов и нативное рассуждение glm-5.3. Своих агентов можно
                добавить в панели слева; отметьте нужных в карточке задачи и
                запустите, в конце страница сравнивает финальные ответы с эталоном.
              </p>
            </header>

            {frozenStamp && !hasLocal && (
              <div className="banner">
                <span>показан замороженный прогон от {frozenStamp}</span>
                <button className="chip-btn" onClick={startOwn}>
                  начать свой прогон
                </button>
              </div>
            )}

            <TaskCard
              task={task}
              setTask={setTask}
              busy={busy}
              hasRuns={hasRuns}
              agents={agents}
              selected={selected}
              onToggle={toggleSel}
              onRun={runSelected}
              onStop={stopAll}
              onReset={startOwn}
            />

            <div className="group-label">выбранные агенты</div>
            <div className="strat-grid">
              {visible.map(a => (
                <AgentCard
                  key={a.id}
                  agent={a}
                  state={runs[a.id]}
                  onRun={() => run(a, task)}
                  busy={busy}
                  builtIn={builtIn}
                />
              ))}
            </div>

            <Compare runs={runs} task={task} agents={agents} selected={selected} />

            <footer className="page-foot">
              агент — это один запрос: инструкция плюс задача; модели glm-4.6
              (thinking выключен) и glm-5.3 (effort low); задача и эталон — в{' '}
              <code>day3/puzzle.py</code>, проверка единственности —{' '}
              <code>day3/verify.py</code>
            </footer>
          </div>
        </main>
      </div>
    </div>
  )
}
