import { formatStamp } from '../lib/format.js'

function ChatRow({ c, currentId, onSelect, onDelete }) {
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

function SummaryRow({ summary, currentId, onSelect }) {
  return (
    <li className="chatlist-pin">
      <button
        type="button"
        className={`chatlist-item${summary.id === currentId ? ' active' : ''}`}
        onClick={() => onSelect(summary.id)}
        title="сообщения фоновых задач планировщика"
      >
        <span className="chatlist-main">
          <span className="chatlist-title">{summary.title}</span>
          <span className="chatlist-prof">планировщик · автоматически</span>
        </span>
        {summary.unread > 0 && (
          <span className="chatlist-unread" aria-label="непрочитанные сообщения">
            {summary.unread}
          </span>
        )}
        <span className="chatlist-date">{formatStamp(summary.updatedAt)}</span>
      </button>
    </li>
  )
}

export default function ChatList({ chats, currentId, onSelect, onNew, onDelete, summary }) {
  const sorted = [...chats]
    .filter(c => c.id !== summary?.id)
    .sort((a, b) => b.updatedAt - a.updatedAt)

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
        {summary && (
          <SummaryRow summary={summary} currentId={currentId} onSelect={onSelect} />
        )}
        {sorted.map(c => (
          <ChatRow key={c.id} c={c} currentId={currentId} onSelect={onSelect} onDelete={onDelete} />
        ))}
      </ul>
    </div>
  )
}
