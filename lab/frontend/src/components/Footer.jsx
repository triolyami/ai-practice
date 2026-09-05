export default function Footer() {
  return (
    <footer>
      <div className="wrap">
        <p>
          Запуск: <kbd>.venv/bin/python lab/server.py</kbd> → открыть{' '}
          <b>http://127.0.0.1:7861</b>
        </p>
        <p>
          Ключ берётся из <b>.env</b> в корне репозитория (GLM_API_KEY). Замороженные
          результаты дня 2: <a href="/day2">/day2</a>
        </p>
        <p>
          Фронтенд — React + Vite · дизайн по протоколу{' '}
          <a href="https://github.com/Leonxlnx/taste-skill" target="_blank" rel="noopener">
            minimalist-ui / taste-skill
          </a>{' '}
          (MIT) · Z.ai API, совместимый с OpenAI SDK
        </p>
      </div>
    </footer>
  )
}
