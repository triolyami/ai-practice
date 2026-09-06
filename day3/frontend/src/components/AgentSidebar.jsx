import { useState } from 'react'
import { EFFORTS, MODELS, PIPELINES, modelEntry, modelLabel, modelWarn } from '../lib/constants.js'

function AgentEditor({ agent, busy, onSave, onDelete, onCancel }) {
  const [name, setName] = useState(agent.name)
  const [instruction, setInstruction] = useState(agent.instruction)
  const [model, setModel] = useState(agent.model)
  const [effort, setEffort] = useState(EFFORTS.includes(agent.effort) ? agent.effort : 'low')
  const valid = name.trim().length > 0
  return (
    <div className="agent-editor">
      <label className="agent-field">
        <span className="mini-label">имя</span>
        <input
          className="input"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="без названия"
        />
      </label>
      <label className="agent-field">
        <span className="mini-label">инструкция</span>
        <textarea
          className="input"
          rows={4}
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          placeholder="пусто — просто задача"
        />
      </label>
      <div className="agent-field">
        <span className="mini-label">модель</span>
        <div className="agent-models">
          {MODELS.map(m => (
            <button
              key={m.id}
              type="button"
              className={`chip-btn${model === m.id ? ' chip-btn--on' : ''}`}
              onClick={() => setModel(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      {modelEntry(model).thinking === 'effort' && (
        <div className="agent-field">
          <span className="mini-label">effort</span>
          <div className="agent-models">
            {EFFORTS.map(e => (
              <button
                key={e}
                type="button"
                className={`chip-btn${effort === e ? ' chip-btn--on' : ''}`}
                onClick={() => setEffort(e)}
              >
                {e}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="agent-editor-actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          disabled={!valid}
          onClick={() => onSave(agent.id, { name: name.trim(), instruction, model, effort })}
        >
          сохранить
        </button>
        {agent.name && (
          <button type="button" className="chip-btn" disabled={busy} onClick={() => onDelete(agent.id)}>
            удалить
          </button>
        )}
        <button type="button" className="chip-btn" onClick={() => onCancel(agent)}>
          отмена
        </button>
      </div>
    </div>
  )
}

function PipelineEditor({ pipeline, overrides, onSave, onCancel }) {
  const [values, setValues] = useState(() => {
    const out = {}
    for (const st of pipeline.steps) out[st.name] = overrides[st.name] ?? st.default
    return out
  })
  const save = () => {
    const diff = {}
    for (const st of pipeline.steps) {
      if (values[st.name] !== st.default) diff[st.name] = values[st.name]
    }
    onSave(pipeline.id, diff)
  }
  return (
    <div className="agent-editor">
      {pipeline.steps.map(st => (
        <label key={st.name} className="agent-field">
          <span className="mini-label">{st.label}</span>
          <textarea
            className="input"
            rows={4}
            value={values[st.name]}
            onChange={e => setValues(prev => ({ ...prev, [st.name]: e.target.value }))}
          />
        </label>
      ))}
      <div className="agent-editor-actions">
        <button type="button" className="btn btn--primary btn--sm" onClick={save}>
          сохранить
        </button>
        <button type="button" className="chip-btn" onClick={onCancel}>
          отмена
        </button>
      </div>
    </div>
  )
}

export default function AgentSidebar({
  agents,
  busy,
  onCreate,
  onSave,
  onDelete,
  onReset,
  pipelineOverrides,
  onSavePipeline,
}) {
  const [editingId, setEditingId] = useState(null)
  const [editingPipe, setEditingPipe] = useState(null)

  const discardUnsaved = () => {
    const prev = agents.find(a => a.id === editingId)
    if (prev && !prev.name) onDelete(prev.id)
  }
  const add = () => {
    discardUnsaved()
    setEditingPipe(null)
    const agent = { id: `a-${Date.now()}`, name: '', instruction: '', model: 'glm-4.6', effort: 'low' }
    onCreate(agent)
    setEditingId(agent.id)
  }
  const cancel = agent => {
    if (!agent.name) onDelete(agent.id)
    setEditingId(null)
  }
  const toggle = agent => {
    if (editingId === agent.id) {
      cancel(agent)
      return
    }
    discardUnsaved()
    setEditingPipe(null)
    setEditingId(agent.id)
  }
  const save = (id, draft) => {
    onSave(id, draft)
    setEditingId(null)
  }
  const remove = id => {
    onDelete(id)
    setEditingId(null)
  }
  const togglePipe = id => {
    if (editingPipe === id) {
      setEditingPipe(null)
      return
    }
    discardUnsaved()
    setEditingId(null)
    setEditingPipe(id)
  }
  const savePipe = (id, steps) => {
    onSavePipeline(id, steps)
    setEditingPipe(null)
  }
  const reset = () => {
    onReset()
    setEditingId(null)
    setEditingPipe(null)
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <span className="side-title">агенты</span>
        <button type="button" className="chip-btn" onClick={add} disabled={busy}>
          + агент
        </button>
      </div>
      <ul className="agent-list">
        {agents.map(a => (
          <li key={a.id}>
            <button
              type="button"
              className={`agent-row agent-row--stack${editingId === a.id ? ' agent-row--active' : ''}`}
              onClick={() => toggle(a)}
              title={a.instruction || 'пусто — просто задача'}
            >
              <span className="agent-name">{a.name || 'без названия'}</span>
              <span className={`strat-model${modelWarn(a.model) ? ' strat-model--warn' : ''}`}>
                {modelLabel(a.model, a.effort)}
              </span>
            </button>
            {editingId === a.id && (
              <AgentEditor
                key={a.id}
                agent={a}
                busy={busy}
                onSave={save}
                onDelete={remove}
                onCancel={cancel}
              />
            )}
          </li>
        ))}
      </ul>
      <span className="side-title">пайплайны</span>
      <ul className="agent-list">
        {PIPELINES.map(p => (
          <li key={p.id}>
            <button
              type="button"
              className={`agent-row agent-row--stack${editingPipe === p.id ? ' agent-row--active' : ''}`}
              onClick={() => togglePipe(p.id)}
              title={p.hint}
            >
              <span className="agent-name">{p.name}</span>
              <span className="strat-model">{modelLabel(p.model)}</span>
            </button>
            {editingPipe === p.id && (
              <PipelineEditor
                key={p.id}
                pipeline={p}
                overrides={pipelineOverrides[p.id] || {}}
                onSave={savePipe}
                onCancel={() => setEditingPipe(null)}
              />
            )}
          </li>
        ))}
      </ul>
      <div className="sidebar-foot">
        <button type="button" className="chip-btn" onClick={reset} disabled={busy}>
          вернуть по умолчанию
        </button>
      </div>
    </aside>
  )
}
