export default function TopBar() {
  const openDay2 = e => {
    e.preventDefault()
    window.open(`http://${location.hostname}:7861/day2`, '_blank')
  }
  return (
    <header className="topbar">
      <div className="topbar-in">
        <a className="brand" href="#">
          AI Practice <em>/ день 3</em>
        </a>
        <div className="toplinks">
          <a className="toplink" href="#" onClick={openDay2}>
            выводы дня 2
          </a>
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
