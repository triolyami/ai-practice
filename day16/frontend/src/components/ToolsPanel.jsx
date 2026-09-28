import { useCallback, useEffect, useState } from 'react'
import { plural } from '../lib/format.js'

function ArgField({ name, prop, required, value, onChange }) {
  const type = prop?.type
  const label = `${name}${required ? ' *' : ''}${type ? ` : ${type}` : ''}`
  return (
    <label className="tool-arg">
      <span className="tool-arg-label" title={prop?.description || ''}>{label}</span>
      {type === 'boolean' ? (
        <input
          type="checkbox"
          checked={!!value}
          onChange={e => onChange(name, e.target.checked)}
        />
      ) : (
        <input
          type="text"
          className="input input--sm mono"
          value={value ?? ''}
          placeholder={type === 'number' || type === 'integer' ? '0' : type && type !== 'string' ? 'JSON' : ''}
          onChange={e => onChange(name, e.target.value)}
        />
      )}
      {prop?.description && <span className="tool-arg-desc">{prop.description}</span>}
    </label>
  )
}

function CallForm({ serverId, tool }) {
  const props = tool.input_schema?.properties || {}
  const required = new Set(tool.input_schema?.required || [])
  const names = Object.keys(props)
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const onChange = (name, v) => setValues(prev => ({ ...prev, [name]: v }))

  const submit = async () => {
    const args = {}
    for (const name of names) {
      const prop = props[name]
      const type = prop?.type
      if (type === 'boolean') {
        if (values[name] !== undefined) args[name] = !!values[name]
        else if (required.has(name)) args[name] = false
        continue
      }
      const str = String(values[name] ?? '').trim()
      if (!str) {
        if (required.has(name)) {
          setResult({ formError: `поле «${name}» обязательно` })
          return
        }
        continue
      }
      if (type === 'number' || type === 'integer') {
        const num = Number(str)
        if (Number.isNaN(num)) {
          setResult({ formError: `«${name}» — не число` })
          return
        }
        args[name] = num
      } else if (!type || type === 'string') {
        args[name] = str
      } else {
        try {
          args[name] = JSON.parse(str)
        } catch {
          setResult({ formError: `«${name}» — не JSON` })
          return
        }
      }
    }
    setBusy(true)
    setResult(null)
    try {
      const res = await fetch('/api/mcp/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server: serverId, tool: tool.name, arguments: args }),
      })
      const data = await res.json()
      if (!res.ok) {
        setResult({ formError: data.error || `HTTP ${res.status}` })
        return
      }
      setResult(data)
    } catch (e) {
      setResult({ formError: `нет связи: ${e.message}` })
    } finally {
      setBusy(false)
    }
  }

  const blocks = result?.content || []
  const text = blocks
    .filter(b => b && b.type === 'text')
    .map(b => b.text)
    .join('\n')
  const otherBlocks = blocks.filter(b => b && b.type !== 'text')

  return (
    <div className="tool-call">
      {names.length > 0 && (
        <div className="tool-args">
          {names.map(name => (
            <ArgField
              key={name}
              name={name}
              prop={props[name]}
              required={required.has(name)}
              value={values[name]}
              onChange={onChange}
            />
          ))}
        </div>
      )}
      <div className="mem-actions">
        <button
          type="button"
          className="mem-btn mem-btn--on"
          disabled={busy}
          onClick={submit}
        >
          {busy ? 'вызываю…' : 'вызвать'}
        </button>
      </div>
      {result?.formError && <div className="tool-result tool-result--err">{result.formError}</div>}
      {result && !result.formError && (
        <div className={`tool-result${result.is_error ? ' tool-result--err' : ''}`}>
          {result.is_error && <span className="tool-result-flag">is_error</span>}
          {text || (otherBlocks.length ? JSON.stringify(otherBlocks, null, 2) : '(пустой результат)')}
        </div>
      )}
    </div>
  )
}

function ToolRow({ serverId, tool }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="tool-row">
      <button type="button" className="tool-open" onClick={() => setOpen(prev => !prev)}>
        <span className="tool-name">{tool.name}</span>
        {tool.description && <span className="tool-desc">{tool.description}</span>}
      </button>
      {open && (
        <div className="tool-body">
          {tool.title && tool.title !== tool.name && <p className="mem-note">{tool.title}</p>}
          <details className="tool-schema-wrap">
            <summary>input_schema</summary>
            <pre className="tool-schema">{JSON.stringify(tool.input_schema || {}, null, 2)}</pre>
          </details>
          <CallForm serverId={serverId} tool={tool} />
        </div>
      )}
    </div>
  )
}

function ServerBlock({ server }) {
  const ok = server.status === 'ok'
  const tools = server.tools || []
  const info = server.server_info || {}
  return (
    <div className="tool-server">
      <div
        className="tool-server-head"
        title={server.error || `подключено, протокол ${server.protocol_version || '—'}`}
      >
        <span className={`tool-dot ${ok ? 'tool-dot--ok' : 'tool-dot--err'}`} />
        <span className="tool-server-name">{info.name || server.id}</span>
        <span className="tool-server-meta">
          {server.id} · {server.transport}
          {server.protocol_version ? ` · протокол ${server.protocol_version}` : ''}
          {info.version ? ` · v${info.version}` : ''}
          {ok ? ` · ${tools.length} ${plural(tools.length, ['инструмент', 'инструмента', 'инструментов'])}` : ''}
        </span>
      </div>
      {server.error && <p className="tool-err">{server.error}</p>}
      {ok && tools.length === 0 && <p className="sum-empty">соединение есть, инструментов нет</p>}
      {tools.map(t => <ToolRow key={t.name} serverId={server.id} tool={t} />)}
    </div>
  )
}

export default function ToolsPanel() {
  const [servers, setServers] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/mcp')
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      setServers(data.servers || [])
      setError(null)
    } catch (e) {
      setError(`не удалось получить /api/mcp: ${e.message}`)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <section className="ctx-panel">
      <div className="mem-sec-head">
        <span className="mini-label">mcp-инструменты</span>
        <button type="button" className="mem-btn" onClick={load}>обновить</button>
      </div>
      {error && <p className="tool-err">{error}</p>}
      {servers === null && !error && <p className="sum-empty">читаю реестр…</p>}
      {(servers || []).map(s => <ServerBlock key={s.id} server={s} />)}
      {servers !== null && servers.length === 0 && (
        <p className="sum-empty">реестр пуст — смотри MCP_SERVERS в config.py</p>
      )}
      <p className="mem-note">
        реестр MCP_SERVERS в config.py · соединения живут в отдельном потоке
        с asyncio-циклом и не зависят от чата
      </p>
    </section>
  )
}
