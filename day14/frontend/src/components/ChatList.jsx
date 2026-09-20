import { formatStamp } from '../lib/format.js'
import { ENFORCE_LABEL, invariantLabel } from '../lib/constants.js'

function ChatRow({ c, invariants, currentId, onSelect, onDelete }) {
  const inv = invariantLabel(invariants, c.invariant)
  return (
    <li>
      <button
        type="button"
        className={`chatlist-item${c.id === currentId ? ' active' : ''}`}
        onClick={() => onSelect(c.id)}
        title={c.title}
      >
        <span className="chatlist-main">
          <span className="chatlist-title">{c.title || 'без названия'}</span>
          {inv && <span className="chatlist-prof">инварианты · {inv}{c.enforce && c.enforce !== 'prompt' ? ` · ${ENFORCE_LABEL[c.enforce]}` : ''}</span>}
        </span>
        <span className="chatlist-date">{formatStamp(c.updatedAt)}</span>
      </button>
      <button
        type="button"
        className="chatlist-del"
        aria-label="Удалить чат"
        onClick={e => { e.stopPropagation(); onDelete(c.id) }}
      >
        ×
      </button>
    </li>
  )
}

export default function ChatList({ chats, invariants, currentId, onSelect, onNew, onDelete }) {
  const sorted = [...chats].sort((a, b) => b.updatedAt - a.updatedAt)

  return (
    <div className="chatlist">
      <div className="chatlist-head">
        <span className="side-title">чаты</span>
        <button type="button" className="chatlist-new" onClick={() => onNew()}>+ новый</button>
      </div>
      {sorted.length === 0 && (
        <p className="chatlist-empty">пока пусто — начните первый диалог</p>
      )}
      <ul className="chatlist-items">
        {sorted.map(c => (
          <ChatRow key={c.id} c={c} invariants={invariants} currentId={currentId} onSelect={onSelect} onDelete={onDelete} />
        ))}
      </ul>
    </div>
  )
}
