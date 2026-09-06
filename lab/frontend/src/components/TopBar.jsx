export default function TopBar({ onNewChat, hasChat }) {
  return (
    <header className="topbar">
      <div className="topbar-in">
        <a className="brand" href="#">
          AI Practice <em>/ чат-лаборатория</em>
        </a>
        <div className="toplinks">
          <button
            type="button"
            className="toplink toplink--btn"
            onClick={onNewChat}
            disabled={!hasChat}
          >
            новый чат
          </button>
          <a className="toplink" href="/day2">день 2</a>
          <a
            className="toplink"
            href="https://github.com/triolyami/ai-practice"
            target="_blank"
            rel="noopener"
          >
            repo
          </a>
        </div>
      </div>
    </header>
  )
}
