import { formatStamp } from '../lib/format.js'
import { profileLabel } from '../lib/constants.js'

function ChatRow({ c, profiles, currentId, onSelect, onDelete }) {
  const prof = profileLabel(profiles, c.profile)
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
          {prof && <span className="chatlist-prof">профиль · {prof}</span>}
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

export default function ChatList({ chats, profiles, currentId, onSelect, onNew, onDelete }) {
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
          <ChatRow key={c.id} c={c} profiles={profiles} currentId={currentId} onSelect={onSelect} onDelete={onDelete} />
        ))}
      </ul>
    </div>
  )
}
