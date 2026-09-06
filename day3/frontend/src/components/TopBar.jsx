export default function TopBar() {
  const host = location.hostname
  return (
    <header className="topbar">
      <div className="topbar-in">
        <a className="brand" href="#">
          AI Practice
        </a>
        <nav className="toplinks">
          <a className="toplink" href={`http://${host}:7860`}>
            день 1
          </a>
          <a className="toplink" href={`http://${host}:7861/day2`}>
            день 2
          </a>
          <span className="toplink toplink--on">день 3</span>
        </nav>
        <a
          className="toplink"
          href="https://github.com/triolyami/ai-practice"
          target="_blank"
          rel="noopener"
        >
          repo
        </a>
      </div>
    </header>
  )
}
