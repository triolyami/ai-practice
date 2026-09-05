import { useRef, useState } from 'react'
import { useRun } from './hooks/useRun.js'
import { buildPayload, DEFAULT_CONFIG } from './lib/constants.js'
import TopBar from './components/TopBar.jsx'
import Hero from './components/Hero.jsx'
import Console from './components/Console.jsx'
import Results from './components/Results.jsx'
import Footer from './components/Footer.jsx'

export default function App() {
  const [config, setConfig] = useState(DEFAULT_CONFIG)
  const { run, start, stop } = useRun()
  const resultsRef = useRef(null)

  const patchControl = (name, patch) => setConfig(prev => ({
    ...prev,
    controls: { ...prev.controls, [name]: { ...prev.controls[name], ...patch } },
  }))

  const setField = (name, value) => setConfig(prev => ({ ...prev, [name]: value }))

  const runCount = 1
    + (config.controls.format.enabled ? 2 : 0)
    + (config.controls.length.enabled ? 2 : 0)
    + (config.controls.stop.enabled ? 2 : 0)

  const running = run.phase === 'running'
  const promptReady = config.prompt.trim().length > 0

  const startRun = () => {
    if (!promptReady || running) return
    start(buildPayload(config))
    requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth' }))
  }

  return (
    <>
      <TopBar />
      <main className="wrap">
        <Hero />
        <section className="section" id="setup" style={{ paddingTop: 0 }}>
          <div className="sec-head">
            <span className="sec-num">01</span>
            <h2>Настройка прогона</h2>
          </div>
          <p className="sec-q">
            Введите запрос, выберите модель и оставьте включёнными те ограничители,
            которые хотите сравнить.
          </p>
          <Console
            config={config}
            setField={setField}
            patchControl={patchControl}
            runCount={runCount}
            running={running}
            promptReady={promptReady}
            onRun={startRun}
          />
        </section>
        <section className="section" id="results-section" ref={resultsRef}>
          <div className="sec-head">
            <span className="sec-num">02</span>
            <h2>Результаты</h2>
          </div>
          <p className="sec-q">
            Каждая карточка — отдельный запрос к модели: слева в паре «просьба словами»,
            справа «гарантия параметром».
          </p>
          <Results
            run={run}
            runCount={runCount}
            promptReady={promptReady}
            onStop={stop}
            onRerun={startRun}
          />
        </section>
      </main>
      <Footer />
    </>
  )
}
