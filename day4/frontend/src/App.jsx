import { useEffect, useRef, useState } from 'react'
import TopBar from './components/TopBar.jsx'
import PromptCard from './components/PromptCard.jsx'
import { Lane } from './components/Lane.jsx'
import Conclusions from './components/Conclusions.jsx'
import { runId, useRuns, IDLE } from './hooks/useRuns.js'
import {
  DEFAULT_PROMPT,
  EFFORTS,
  MODELS,
  laneTemperatures,
} from './lib/constants.js'
import { loadState, saveState } from './lib/storage.js'

const defaultTemps = () =>
  Object.fromEntries(Object.entries(MODELS).map(([id, m]) => [id, m.defaultTemperatures.map(String)]))

export default function App() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [model, setModel] = useState('glm-4.6')
  const [samples, setSamples] = useState(3)
  const [effort, setEffort] = useState('low')
  const [tempInputs, setTempInputs] = useState(defaultTemps)
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
      if (EFFORTS.includes(saved.effort)) setEffort(saved.effort)
      if (saved.temps && typeof saved.temps === 'object') {
        setTempInputs(prev => {
          const next = { ...prev }
          for (const [id, list] of Object.entries(saved.temps)) {
            if (MODELS[id] && Array.isArray(list) && list.length && list.every(x => typeof x === 'string')) {
              next[id] = list
            }
          }
          return next
        })
      }
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
      saveState({ prompt, model, samples, effort, temps: tempInputs, runs: doneRuns })
    }, 400)
    return () => clearTimeout(t)
  }, [prompt, model, samples, effort, tempInputs, ready, runs])

  const temperatures = laneTemperatures(tempInputs[model])
  const busy = job != null
  const effectivePrompt = prompt.trim() || DEFAULT_PROMPT
  const laneNote =
    MODELS[model].thinking === 'effort'
      ? `${MODELS[model].label} · effort: ${effort}`
      : `${MODELS[model].label} · рассуждения отключены`

  const start = async () => {
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        if (laneTopRef.current) {
          laneTopRef.current.scrollIntoView({ behavior: 'instant', block: 'start' })
        }
      }),
    )
    await runAll(model, temperatures, samples, effectivePrompt, effort)
  }

  const rerun = (temperature, sample) => {
    runOne(model, temperature, sample, effectivePrompt, effort)
  }

  return (
    <div className="app">
      <TopBar />
      <div className="page-scroll">
        <div className="col">
          <div className="hero">
            <h1>Температура</h1>
            <p className="lead">
              Один и тот же запрос в нескольких температурных точках — по умолчанию 0, 0.7 и максимум
              модели, значения можно менять. Сравниваем точность, креативность и разнообразие;
              прогоны идут параллельно. При первом открытии загружаются замороженные прогоны —
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
            effort={effort}
            onEffortChange={setEffort}
            temps={tempInputs[model]}
            onTempsChange={list => setTempInputs(prev => ({ ...prev, [model]: list }))}
            job={job}
            onStart={start}
            onStop={stop}
          />
          <div ref={laneTopRef} className="lanes">
            {temperatures.map(t => (
              <Lane
                key={`${model}|${t}`}
                temperature={t}
                note={laneNote}
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
