import { useState } from 'react'

function AgentEditor({ agent, busy, onSave, onDelete, onCancel }) {
  const [name, setName] = useState(agent.name)
  const [instruction, setInstruction] = useState(agent.instruction)
  const [model, setModel] = useState(agent.model)
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
          {['glm-4.6', 'glm-5.3'].map(m => (
            <button
              key={m}
              type="button"
              className={`chip-btn${model === m ? ' chip-btn--on' : ''}`}
              onClick={() => setModel(m)}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      <div className="agent-editor-actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          disabled={!valid}
          onClick={() => onSave(agent.id, { name: name.trim(), instruction, model })}
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

export default function AgentSidebar({ agents, busy, onCreate, onSave, onDelete, onReset }) {
  const [editingId, setEditingId] = useState(null)

  const discardUnsaved = () => {
    const prev = agents.find(a => a.id === editingId)
    if (prev && !prev.name) onDelete(prev.id)
  }
  const add = () => {
    discardUnsaved()
    const agent = { id: `a-${Date.now()}`, name: '', instruction: '', model: 'glm-4.6' }
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
  const reset = () => {
    onReset()
    setEditingId(null)
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
              className={`agent-row${editingId === a.id ? ' agent-row--active' : ''}`}
              onClick={() => toggle(a)}
              title={a.instruction || 'пусто — просто задача'}
            >
              <span className="agent-name">{a.name || 'без названия'}</span>
              <span className={`strat-model${a.model === 'glm-5.3' ? ' strat-model--warn' : ''}`}>
                {a.model}
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
      <div className="sidebar-foot">
        <button type="button" className="chip-btn" onClick={reset} disabled={busy}>
          вернуть по умолчанию
        </button>
      </div>
    </aside>
  )
}
