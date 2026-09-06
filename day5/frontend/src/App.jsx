import { useCallback, useEffect, useRef, useState } from 'react'
import TopBar from './components/TopBar.jsx'
import PromptCard from './components/PromptCard.jsx'
import ModelCard from './components/ModelCard.jsx'
import JudgeCard from './components/JudgeCard.jsx'
import { useRuns, IDLE } from './hooks/useRuns.js'
import { DEFAULT_PROMPT, MODELS } from './lib/constants.js'
import { loadState, saveState } from './lib/storage.js'

const ALL_MODELS = Object.keys(MODELS)

export default function App() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [models, setModels] = useState(ALL_MODELS)
  const [judge, setJudge] = useState(null)
  const [judgeMeta, setJudgeMeta] = useState(null)
  const [judging, setJudging] = useState(false)
  const [judgeError, setJudgeError] = useState(null)
  const [ready, setReady] = useState(false)
  const { runs, replaceAll, runOne, runAll, stop, job } = useRuns()
  const cardsTopRef = useRef(null)
  const judgeGenRef = useRef(0)
  const seededRef = useRef(false)

  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    const saved = loadState()
    if (saved) {
      setPrompt(saved.prompt)
      const savedModels = Array.isArray(saved.models) ? saved.models.filter(id => MODELS[id]) : []
      if (savedModels.length) setModels(savedModels)
      const restored = {}
      for (const [id, r] of Object.entries(saved.runs || {})) {
        if (MODELS[id] && r && r.text) {
          restored[id] = { ...IDLE, status: 'done', text: r.text, meta: r.meta }
        }
      }
      replaceAll(restored)
      if (saved.judge && saved.judge.ranking) {
        setJudge(saved.judge)
        setJudgeMeta(saved.judgeMeta || null)
      }
    }
    setReady(true)
  }, [replaceAll])

  useEffect(() => {
    if (!ready) return
    const t = setTimeout(() => {
      const doneRuns = {}
      for (const [id, r] of Object.entries(runs)) {
        if (r.status === 'done') doneRuns[id] = { text: r.text, meta: r.meta }
      }
      saveState({ prompt, models, runs: doneRuns, judge, judgeMeta })
    }, 400)
    return () => clearTimeout(t)
  }, [prompt, models, runs, judge, judgeMeta, ready])

  const busy = job != null
  const inFlight = busy || Object.values(runs).some(r => r.status === 'running')
  const effectivePrompt = prompt.trim() || DEFAULT_PROMPT

  const clearJudge = useCallback(() => {
    judgeGenRef.current += 1
    setJudge(null)
    setJudgeMeta(null)
    setJudgeError(null)
  }, [])

  const toggleModel = id =>
    setModels(prev => (prev.includes(id) ? prev.filter(m => m !== id) : [...ALL_MODELS.filter(m => prev.includes(m) || m === id)]))

  const start = async () => {
    clearJudge()
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        if (cardsTopRef.current) {
          cardsTopRef.current.scrollIntoView({ behavior: 'instant', block: 'start' })
        }
      }),
    )
    await runAll(models, effectivePrompt)
  }

  const rerun = model => {
    clearJudge()
    runOne(model, effectivePrompt)
  }

  const doneSelected = models.filter(id => runs[id]?.status === 'done' && runs[id].text)

  const askJudge = async () => {
    if (doneSelected.length < 2) return
    const gen = judgeGenRef.current
    setJudging(true)
    setJudgeError(null)
    try {
      const res = await fetch('/api/judge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: effectivePrompt,
          answers: doneSelected.map(id => ({
            id,
            text: runs[id].text,
            meta: {
              latency_ms: runs[id].meta?.latency_ms ?? null,
              completion_tokens: runs[id].meta?.completion_tokens ?? null,
              cost_usd: runs[id].meta?.cost_usd ?? null,
            },
          })),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (gen !== judgeGenRef.current) return
      if (!res.ok) {
        setJudgeError(data.error || `HTTP ${res.status}`)
      } else {
        setJudge(data.judge)
        setJudgeMeta(data.meta || null)
      }
    } catch (err) {
      if (gen === judgeGenRef.current) setJudgeError(err.message)
    } finally {
      if (gen === judgeGenRef.current) setJudging(false)
    }
  }

  return (
    <div className="app">
      <TopBar />
      <div className="page-scroll">
        <div className="col">
          <div className="hero">
            <h1>Один запрос — три модели</h1>
            <p className="lead">
              Свой запрос уходит выбранным моделям линейки Z.ai — от бесплатной glm-4.5-flash до
              флагмана glm-5.3. Замеряются время до первого токена, полная латентность, токены и
              стоимость по опубликованным ценам, а слепой судья glm-5.3 решает, какой ответ лучше.
              Замороженный прогон с выводами — по ссылке сверху.
            </p>
          </div>
          <PromptCard
            prompt={prompt}
            onPromptChange={setPrompt}
            models={models}
            onToggleModel={toggleModel}
            job={job}
            inFlight={inFlight}
            onStart={start}
            onStop={stop}
          />
          <div ref={cardsTopRef} className="cards">
            {models.map(id => (
              <ModelCard
                key={id}
                model={id}
                spec={MODELS[id]}
                run={runs[id] || { ...IDLE }}
                busy={busy}
                judged={judge}
                onRerun={rerun}
              />
            ))}
          </div>
          <JudgeCard
            judge={judge}
            meta={judgeMeta}
            judging={judging}
            error={judgeError}
            hasEnough={doneSelected.length >= 2}
            onJudge={askJudge}
            busy={busy}
          />
          <footer className="page-foot">
            Сервер: .venv/bin/python day5/server.py → :7864 · замороженный прогон: day5/experiment.py
            · выводы и цены: <a href="/day5">/day5</a> · промпты по умолчанию: day5/prompts.py
          </footer>
        </div>
      </div>
    </div>
  )
}
