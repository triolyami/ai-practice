import { useRef, useState } from 'react'

// Подсказка для дорожки 1: тот же конвейер, но оркеструет модель в чате.
export const PIPELINE_PROMPT =
  'Вызови по очереди инструменты pipeline: сначала pipeline__search по запросу «композиция MCP», ' +
  'потом передай его результат целиком в pipeline__summarize, ' +
  'потом сохрани дайджест через pipeline__save_to_file в файл digest. Не переписывай текст между шагами.'

const STAGE_LABEL = { search: 'получает данные', summarize: 'обрабатывает', save_to_file: 'сохраняет' }

function StageBox({ s }) {
  const badge =
    s.hop_exact == null ? null
      : s.hop_exact ? <span className="pipe-badge pipe-badge--ok">хоп дословно</span>
        : <span className="pipe-badge pipe-badge--warn">хоп изменён</span>
  return (
    <details className="phase" open={s.ok === false}>
      <summary>
        {s.i + 1}. {s.tool} <span className="pipe-stage-note">{STAGE_LABEL[s.tool]}</span>
        {' — '}{s.ok ? 'ok' : 'ошибка'} {badge}
      </summary>
      <div className="phase-text">
        вход: {JSON.stringify(s.input)}
        {'\n\n'}выход: {s.output}
      </div>
    </details>
  )
}

export default function PipelineCard({ onSuggest }) {
  const [query, setQuery] = useState('композиция MCP')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(null)      // 'code' | 'composite' | null
  const [stages, setStages] = useState([])
  const [verdict, setVerdict] = useState(null) // 'exact' | 'differs' | 'error' | 'na'
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  const runCode = async () => {
    abortRef.current?.abort()
    const ctl = new AbortController()
    abortRef.current = ctl
    setBusy('code'); setStages([]); setVerdict(null); setError(null)
    try {
      const res = await fetch('/api/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), name: name.trim() || undefined }),
        signal: ctl.signal,
      })
      if (!res.ok) {
        const j = await res.json().catch(() => ({}))
        throw new Error(j.error || `HTTP ${res.status}`)
      }
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, idx).trim()
          buf = buf.slice(idx + 1)
          if (!line) continue
          const ev = JSON.parse(line)
          if (ev.event === 'stage') {
            setStages(prev => [...prev, ev])
          } else if (ev.event === 'done') {
            setVerdict(ev.ok ? ev.verdict : `error@${ev.failed_stage}`)
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const runComposite = async () => {
    abortRef.current?.abort()
    setBusy('composite'); setStages([]); setVerdict(null); setError(null)
    try {
      const res = await fetch('/api/mcp/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server: 'pipeline', tool: 'run_pipeline', arguments: { query: query.trim() } }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      const text = (data.content || []).filter(b => b.type === 'text').map(b => b.text).join('\n')
      setStages([{ i: 0, tool: 'run_pipeline', input: { query: query.trim() }, output: text, ok: !data.is_error, hop_exact: null }])
      setVerdict('na')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="ctx-panel">
      <div className="mem-sec-head">
        <span className="mini-label">кодовый пайплайн</span>
      </div>
      <p className="mem-note">
        search → summarize → save_to_file. Инструменты изолированы — цепочку
        собирает хост: код (кнопка ниже) или модель в чате.
      </p>
      <div className="tool-args">
        <label className="tool-arg">
          <span className="tool-arg-label">запрос *</span>
          <input className="input input--sm" value={query} onChange={e => setQuery(e.target.value)} />
        </label>
        <label className="tool-arg">
          <span className="tool-arg-label">имя файла</span>
          <input className="input input--sm mono" value={name} placeholder="auto" onChange={e => setName(e.target.value)} />
        </label>
      </div>
      <div className="mem-actions">
        <button type="button" className="mem-btn mem-btn--on" disabled={!!busy || !query.trim()} onClick={runCode}>
          {busy === 'code' ? 'пайплайн…' : 'запустить пайплайн'}
        </button>
        <button type="button" className="mem-btn" disabled={!!busy || !query.trim()} onClick={runComposite}
          title="один инструмент внутри сервера — контрольная дорожка">
          {busy === 'composite' ? 'вызываю…' : 'композитный'}
        </button>
      </div>
      <div className="mem-actions">
        <button type="button" className="mem-btn" onClick={() => onSuggest?.(PIPELINE_PROMPT)}
          title="подставить в поле ввода чата подсказку для модели">
          дорожка модели → в чат
        </button>
      </div>
      {error && <p className="tool-err">{error}</p>}
      {stages.map((s, i) => <StageBox key={i} s={s} />)}
      {verdict === 'exact' && (
        <p className="pipe-verdict pipe-verdict--ok">передача данных: exact — байт-в-байт</p>
      )}
      {verdict === 'differs' && (
        <p className="pipe-verdict pipe-verdict--warn">передача данных: differs — хеши разошлись</p>
      )}
      {verdict === 'na' && (
        <p className="pipe-verdict">передача данных: n/a — хопов на уровне MCP нет, всё внутри одного вызова</p>
      )}
      {verdict?.startsWith('error@') && (
        <p className="pipe-verdict pipe-verdict--warn">цепочка упала на этапе {Number(verdict.slice(6)) + 1}</p>
      )}
    </section>
  )
}
