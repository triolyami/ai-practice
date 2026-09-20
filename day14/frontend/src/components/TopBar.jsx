import { COUNTER_BUILD } from '../lib/constants.js'

export default function TopBar() {
  return (
    <header className="topbar">
      <div className="topbar-in">
        <a className="brand" href="#">
          AI Practice <em>/ день 14 · инварианты</em>
        </a>
        <div className="toplinks">
          <span
            className="toplink"
            style={{ cursor: 'default' }}
            title={`счётчик контекста: промпт + ответ по факту API, сборка ${COUNTER_BUILD}. Если видите другой номер сборки — страница загружена раньше обновления, обновите вкладку.`}
          >
            счёт: промпт+ответ · сборка {COUNTER_BUILD}
          </span>
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
