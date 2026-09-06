import { useEffect, useRef, useState } from 'react'
import TopBar from './components/TopBar.jsx'
import PromptCard from './components/PromptCard.jsx'
import { Lane } from './components/Lane.jsx'
import Conclusions from './components/Conclusions.jsx'
import { runId, useRuns, IDLE } from './hooks/useRuns.js'
import { DEFAULT_PROMPT, MODELS } from './lib/constants.js'
import { loadState, saveState } from './lib/storage.js'

export default function App() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [model, setModel] = useState('glm-4.6')
  const [samples, setSamples] = useState(3)
  const [ready, setReady] = useState(false)
  const { runs, replaceAll, runOne, runAll, stop, job } = useRuns()
  const laneTopRef = useRef(null)
  const seededRef = useRef(false)

  useEffect(() => {
    if (seededRef.current) return
    seededRef.current = true
    const saved = loadState()
    if (saved) {
      setPrompt(saved.prompt)
      if (MODELS[saved.model]) setModel(saved.model)
      if (typeof saved.samples === 'number') setSamples(saved.samples)
      const restored = {}
      for (const [id, r] of Object.entries(saved.runs || {})) {
        restored[id] = { ...IDLE, status: 'done', text: r.text, meta: r.meta, seeded: !!r.seeded }
      }
      replaceAll(restored)
      setReady(true)
      return
    }
    fetch('/results.json')
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (data && Array.isArray(data.runs)) {
          const restored = {}
          for (const r of data.runs) {
            restored[runId(r.model, r.temperature, r.sample)] = {
              status: 'done',
              text: r.content,
              meta: {
                model: r.model,
                temperature: r.temperature,
                finish_reason: r.finish_reason,
                prompt_tokens: r.prompt_tokens,
                completion_tokens: r.completion_tokens,
                latency_ms: r.latency_ms,
              },
              seeded: true,
            }
          }
          replaceAll(restored)
          if (typeof data.meta?.prompt === 'string') setPrompt(data.meta.prompt)
        }
      })
      .catch(() => {})
      .finally(() => setReady(true))
  }, [replaceAll])

  useEffect(() => {
    if (!ready) return
    const t = setTimeout(() => {
      const doneRuns = {}
      for (const [id, r] of Object.entries(runs)) {
        if (r.status === 'done') doneRuns[id] = { text: r.text, meta: r.meta, seeded: r.seeded }
      }
      saveState({ prompt, model, samples, runs: doneRuns })
    }, 400)
    return () => clearTimeout(t)
  }, [prompt, model, samples, ready, runs])

  const temperatures = MODELS[model].temperatures
  const busy = job != null
  const effectivePrompt = prompt.trim() || DEFAULT_PROMPT

  const start = async () => {
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        if (laneTopRef.current) {
          laneTopRef.current.scrollIntoView({ behavior: 'instant', block: 'start' })
        }
      }),
    )
    await runAll(model, temperatures, samples, effectivePrompt)
  }

  const rerun = (temperature, sample) => {
    runOne(model, temperature, sample, effectivePrompt)
  }

  return (
    <div className="app">
      <TopBar />
      <div className="page-scroll">
        <div className="col">
          <div className="hero">
            <h1>Температура</h1>
            <p className="lead">
              Один и тот же запрос при temperature = 0, 0.7 и 1.2: сравниваем точность,
              креативность и разнообразие. При первом открытии загружаются замороженные прогоны —
              любой из них можно перезапустить вживую.
            </p>
          </div>
          <PromptCard
            prompt={prompt}
            onPromptChange={setPrompt}
            model={model}
            onModelChange={setModel}
            samples={samples}
            onSamplesChange={setSamples}
            job={job}
            onStart={start}
            onStop={stop}
          />
          <div ref={laneTopRef} className="lanes">
            {temperatures.map(t => (
              <Lane
                key={`${model}|${t}`}
                temperature={t}
                items={Array.from({ length: samples }, (_, i) => runs[runId(model, t, i + 1)] || { ...IDLE })}
                busy={busy}
                onRerun={rerun}
              />
            ))}
          </div>
          <Conclusions />
          <footer className="page-foot">
            Сервер: .venv/bin/python day4/server.py → :7863 · замороженные прогоны: day4/run_matrix.py
            · данные: day4/results.json
          </footer>
        </div>
      </div>
    </div>
  )
}
