export default function TopBar() {
  return (
    <header className="topbar">
      <div className="wrap topbar-in">
        <a className="brand" href="#">
          AI Practice <em>/ лаборатория</em>
        </a>
        <div className="toplinks">
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
