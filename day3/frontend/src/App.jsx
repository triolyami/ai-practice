import { useCallback, useEffect, useRef, useState } from 'react'
import { useRuns } from './hooks/useRuns.js'
import { useAgents } from './hooks/useAgents.js'
import { usePipelines, resolveSteps } from './hooks/usePipelines.js'
import { DEFAULT_AGENTS, DEFAULT_TASK, PIPELINES } from './lib/constants.js'
import { clearState, loadState, saveState } from './lib/storage.js'
import { requestJudge } from './lib/judge.js'
import TopBar from './components/TopBar.jsx'
import TaskCard from './components/TaskCard.jsx'
import AgentCard from './components/AgentCard.jsx'
import AgentSidebar from './components/AgentSidebar.jsx'
import Compare from './components/Compare.jsx'

export default function App() {
  const { agents, setAgents } = useAgents()
  const { pipelines: pipeOverrides, update: savePipelineOverrides, resetPipelines } = usePipelines()
  const [task, setTask] = useState(DEFAULT_TASK)
  const [frozenAt, setFrozenAt] = useState(null)
  const [selected, setSelected] = useState(() => agents.map(a => a.id))
  const { runs, replaceAll, run, abort, drop } = useRuns()
  const persistRef = useRef('')
  const [judge, setJudge] = useState(null)

  const universe = [
    ...agents.map(a => ({ ...a, kind: 'agent' })),
    ...PIPELINES.map(p => ({
      kind: 'pipeline',
      id: p.id,
      name: p.name,
      model: p.model,
      hint: p.hint,
      instructions: resolveSteps(p.id, pipeOverrides),
    })),
  ]

  useEffect(() => {
    const ids = new Set([...agents.map(a => a.id), ...PIPELINES.map(p => p.id)])
    const saved = loadState()
    if (saved) {
      setTask(saved.task)
      replaceAll(saved.runs)
      if (saved.judge) setJudge({ status: 'done', ...saved.judge })
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
    const judgeState =
      judge?.status === 'done' ? { result: judge.result, task: judge.task, count: judge.count } : null
    const json = JSON.stringify({ task, runs: terminal, judge: judgeState })
    if (json === persistRef.current) return
    persistRef.current = json
    saveState({ task, runs: terminal, judge: judgeState })
  }, [runs, task, judge])

  const busy = Object.values(runs).some(r => r.status === 'running')
  const judgeBusy = judge?.status === 'running'
  const judgeCandidates = universe
    .filter(u => selected.includes(u.id) && runs[u.id]?.status === 'done' && runs[u.id]?.text?.trim())
    .map(u => ({ id: u.id, name: u.name || u.id, text: runs[u.id].text.slice(0, 12000) }))
  const hasLocal = Object.values(runs).some(
    r => !r.frozen && (r.status === 'done' || r.status === 'error'),
  )
  const hasRuns = Object.keys(runs).length > 0

  const toggleSel = useCallback(id => {
    setSelected(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]))
  }, [])

  const runMany = useCallback(
    async list => {
      await Promise.all(list.map(item => run(item, task)))
    },
    [run, task],
  )

  const runSelected = useCallback(() => {
    const list = universe.filter(u => selected.includes(u.id))
    if (!list.length) return
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document.getElementById(`strat-${list[0].id}`)?.scrollIntoView({ block: 'start' })
      })
    })
    runMany(list)
  }, [runMany, selected, universe])

  const stopAll = useCallback(() => {
    abort()
  }, [abort])

  const runJudgeAction = useCallback(async () => {
    if (judgeCandidates.length < 2) return
    setJudge({ status: 'running' })
    try {
      const result = await requestJudge({ task, answers: judgeCandidates })
      setJudge({ status: 'done', result, task, count: judgeCandidates.length })
    } catch (err) {
      setJudge({ status: 'error', error: err.message })
    }
  }, [judgeCandidates, task])

  const startOwn = useCallback(() => {
    abort()
    clearState()
    persistRef.current = ''
    replaceAll({})
    setTask(DEFAULT_TASK)
    setFrozenAt(null)
    setJudge(null)
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

  const resetAll = useCallback(() => {
    const fresh = DEFAULT_AGENTS.map(a => ({ ...a }))
    const ids = new Set(fresh.map(a => a.id))
    setAgents(fresh)
    resetPipelines()
    setSelected(fresh.map(a => a.id))
    replaceAll(Object.fromEntries(Object.entries(runs).filter(([id]) => ids.has(id))))
  }, [replaceAll, resetPipelines, runs, setAgents])

  const frozenStamp = frozenAt
    ? new Date(frozenAt).toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : null

  const builtIn = task.trim() === DEFAULT_TASK.trim()
  const visible = universe.filter(u => selected.includes(u.id))

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
          onReset={resetAll}
          pipelineOverrides={pipeOverrides}
          onSavePipeline={savePipelineOverrides}
        />
        <main className="page-scroll">
          <div className="col">
            <header className="hero">
              <h1>Реши одну задачу несколькими способами</h1>
              <p className="lead">
                Одна логическая задача решается через API агентами: у каждого —
                своя инструкция и модель, запуск — один запрос. Четыре агента
                встроены по заданию: прямой ответ, пошаговое решение, группа
                экспертов и нативное рассуждение glm-5.3. Своих агентов и правки
                пайплайнов — в панели слева; отметьте нужное в карточке задачи и
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
              universe={universe}
              selected={selected}
              onToggle={toggleSel}
              onRun={runSelected}
              onStop={stopAll}
              onReset={startOwn}
            />

            <div className="group-label">выбранные агенты и пайплайны</div>
            <div className="strat-grid">
              {visible.map(u => (
                <AgentCard
                  key={u.id}
                  item={u}
                  state={runs[u.id]}
                  onRun={() => run(u, task)}
                  busy={busy}
                  builtIn={builtIn}
                />
              ))}
            </div>

            <Compare
              runs={runs}
              task={task}
              universe={universe}
              selected={selected}
              judge={judge}
              onJudge={runJudgeAction}
              judgeBusy={busy || judgeBusy}
              judgeCandidates={judgeCandidates}
            />

            <footer className="page-foot">
              агент — это один запрос: инструкция плюс задача; пайплайн —
              несколько шагов подряд, шаги фиксированы, правятся только
              инструкции; модели glm-4.6 (thinking выключен) и glm-5.3
              (effort low); задача и эталон — в <code>day3/puzzle.py</code>,
              проверка единственности — <code>day3/verify.py</code>
            </footer>
          </div>
        </main>
      </div>
    </div>
  )
}
