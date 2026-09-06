import { useCallback, useEffect, useRef, useState } from 'react'
import { useRuns } from './hooks/useRuns.js'
import { DEFAULT_TASK, EXTRA_ORDER, MAIN_ORDER, STRATEGIES } from './lib/constants.js'
import { clearState, loadState, saveState } from './lib/storage.js'
import TopBar from './components/TopBar.jsx'
import TaskCard from './components/TaskCard.jsx'
import StrategyCard from './components/StrategyCard.jsx'
import Compare from './components/Compare.jsx'

export default function App() {
  const [task, setTask] = useState(DEFAULT_TASK)
  const [frozenAt, setFrozenAt] = useState(null)
  const { runs, replaceAll, run, abort } = useRuns()
  const stopRef = useRef(false)
  const persistRef = useRef('')

  useEffect(() => {
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

  const runMany = useCallback(
    async ids => {
      stopRef.current = false
      for (const id of ids) {
        if (stopRef.current) break
        await run(id, task)
      }
    },
    [run, task],
  )

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
  }, [abort, replaceAll])

  const frozenStamp = frozenAt
    ? new Date(frozenAt).toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : null

  const builtIn = task.trim() === DEFAULT_TASK.trim()

  return (
    <div className="app">
      <TopBar />
      <main className="page-scroll">
        <div className="col">
          <header className="hero">
            <span className="pill">день 3 · разные способы рассуждения</span>
            <h1>Четыре способа решить одну задачу</h1>
            <p className="lead">
              Одна логическая задача решается через API четырьмя способами из
              задания: прямой ответ, пошаговое решение, предварительный промпт и
              группа экспертов. Ниже — два дополнительных эксперимента:
              мультиагентные эксперты и нативное рассуждение glm-5.3. В конце
              страница сравнивает финальные ответы с эталоном.
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
            onRunMain={() => runMany(MAIN_ORDER)}
            onRunExtra={() => runMany(EXTRA_ORDER)}
            onStop={stopAll}
            onReset={startOwn}
          />

          <div className="group-label">способы из задания</div>
          <div className="strat-grid">
            {STRATEGIES.filter(st => st.main).map(st => (
              <StrategyCard
                key={st.id}
                strategy={st}
                state={runs[st.id]}
                onRun={() => run(st.id, task)}
                busy={busy}
                builtIn={builtIn}
              />
            ))}
          </div>

          <div className="group-label">дополнительные эксперименты</div>
          <div className="strat-grid">
            {STRATEGIES.filter(st => !st.main).map(st => (
              <StrategyCard
                key={st.id}
                strategy={st}
                state={runs[st.id]}
                onRun={() => run(st.id, task)}
                busy={busy}
                builtIn={builtIn}
              />
            ))}
          </div>

          <Compare runs={runs} task={task} />

          <footer className="page-foot">
            модели: glm-4.6 (thinking выключен) для способов из задания,
            glm-5.3 (effort low) для нативного рассуждения; задача и эталон — в{' '}
            <code>day3/puzzle.py</code>, проверка единственности —{' '}
            <code>day3/verify.py</code>
          </footer>
        </div>
      </main>
    </div>
  )
}
