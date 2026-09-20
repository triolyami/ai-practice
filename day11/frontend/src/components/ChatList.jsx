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
        <span className="chatlist-title">{c.title || 'без названия'}</span>
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

export default function ChatList({ chats, workspaces, currentId, onSelect, onNew, onDelete, onDeleteWorkspace }) {
  const sorted = [...chats].sort((a, b) => b.updatedAt - a.updatedAt)
  const privateChats = sorted.filter(c => !c.workspace)

  const names = []
  for (const w of workspaces || []) if (w.name && !names.includes(w.name)) names.push(w.name)
  for (const c of sorted) {
    if (c.workspace && !names.includes(c.workspace)) names.push(c.workspace)
  }
  const wsByName = Object.fromEntries((workspaces || []).map(w => [w.name, w]))
  const grouped = names.length > 0

  return (
    <div className="chatlist">
      <div className="chatlist-head">
        <span className="side-title">чаты</span>
        <button type="button" className="chatlist-new" onClick={() => onNew('')}>+ новый</button>
      </div>
      {sorted.length === 0 && names.length === 0 && (
        <p className="chatlist-empty">пока пусто — начните первый диалог</p>
      )}

      {!grouped && (
        <ul className="chatlist-items">
          {privateChats.map(c => (
            <ChatRow key={c.id} c={c} currentId={currentId} onSelect={onSelect} onDelete={onDelete} />
          ))}
        </ul>
      )}

      {grouped && (
        <div className="chatlist-groups">
          <div className="chatlist-group">
            <div className="ws-head">
              <span className="ws-name">личная память</span>
              <button
                type="button"
                className="ws-add"
                title="Новый чат с личной рабочей памятью"
                onClick={() => onNew('')}
              >
                +
              </button>
            </div>
            <ul className="chatlist-items">
              {privateChats.map(c => (
                <ChatRow key={c.id} c={c} currentId={currentId} onSelect={onSelect} onDelete={onDelete} />
              ))}
              {privateChats.length === 0 && (
                <li className="ws-empty">нет чатов</li>
              )}
            </ul>
          </div>

          {names.map(name => {
            const ws = wsByName[name]
            const items = sorted.filter(c => c.workspace === name)
            return (
              <div key={name} className="chatlist-group">
                <div className="ws-head">
                  <span className="ws-name" title={ws ? `область ${ws.id}` : name}>{name}</span>
                  <button
                    type="button"
                    className="ws-add"
                    title={`Новый чат в области «${name}» — с общей рабочей памятью`}
                    onClick={() => onNew(name)}
                  >
                    +
                  </button>
                  {ws && (
                    <button
                      type="button"
                      className="ws-del"
                      aria-label={`Удалить область ${name}`}
                      title="Удалить область: рабочая память сотрётся, чаты вернутся к личной"
                      onClick={() => onDeleteWorkspace(ws.id, name)}
                    >
                      ×
                    </button>
                  )}
                </div>
                <ul className="chatlist-items">
                  {items.map(c => (
                    <ChatRow key={c.id} c={c} currentId={currentId} onSelect={onSelect} onDelete={onDelete} />
                  ))}
                  {items.length === 0 && (
                    <li className="ws-empty">нет чатов — область ждёт нового диалога</li>
                  )}
                </ul>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
