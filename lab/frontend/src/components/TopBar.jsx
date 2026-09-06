export default function TopBar() {
  return (
    <header className="topbar">
      <div className="topbar-in">
        <a className="brand" href="#">
          AI Practice <em>/ чат-лаборатория</em>
        </a>
        <div className="toplinks">
          <a className="toplink" href="/day2">выводы</a>
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
