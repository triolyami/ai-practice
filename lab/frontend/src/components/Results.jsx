import { plural, prefixLen } from '../lib/format.js'

function badgesFor(item, runs) {
  const m = item.metrics
  const list = []
  if (item.error) return [badge('ошибка запроса', 'red')]
  if (!m.chars && (item.completion_tokens || 0) > 0) {
    list.push(badge('пустой ответ — токены ушли в скрытые рассуждения', 'red'))
    if (item.latency_ms) list.push(badge(`${(item.latency_ms / 1000).toFixed(1)} с`))
    return list
  }
  list.push(badge(`${m.words} ${plural(m.words, ['слово', 'слова', 'слов'])}`))
  list.push(badge(`${item.completion_tokens} ${plural(item.completion_tokens, ['токен', 'токена', 'токенов'])}`))
  if (item.latency_ms) list.push(badge(`${(item.latency_ms / 1000).toFixed(1)} с`))
  if (item.group === 'format') {
    list.push(badge(m.valid_json ? 'валидный JSON' : 'невалидный JSON', m.valid_json ? 'green' : 'red'))
    if (m.markdown_fence) list.push(badge('markdown-ограждение', 'yellow'))
  }
  if (item.group === 'stop') {
    list.push(badge(`${m.paragraphs} ${plural(m.paragraphs, ['абзац', 'абзаца', 'абзацев'])}`))
  }
  if (item.finish_reason === 'length') {
    list.push(badge('finish_reason: length', 'red'))
    if (m.ends_mid_sentence) list.push(badge('обрыв на полуслове', 'red'))
  } else if (item.finish_reason) {
    list.push(badge('finish_reason: ' + item.finish_reason))
  }
  const baseline = runs.baseline
  if (item.id === 'stop-api' && baseline && baseline.metrics.chars) {
    const same = prefixLen(item.content, baseline.content)
    if (same > 0) {
      list.push(badge(
        `совпадение с эталоном: ${same} ${plural(same, ['символ', 'символа', 'символов'])}`,
        same >= 20 ? 'green' : undefined,
      ))
    }
  }
  return list
}

function badge(text, tone) {
  return { text, tone }
}

function tagFor(kind) {
  const labels = { base: 'эталон', prompt: 'промпт', api: 'api-параметр' }
  return labels[kind] || kind
}

function pendingLabel(phase) {
  if (phase === 'stopped') return 'отменено'
  if (phase === 'failed') return 'не выполнено'
  return 'запрос к модели…'
}

function ResultCard({ item, run, runs, phase }) {
  const filled = Boolean(run)
  return (
    <article className={`card${item && run && run.error ? ' card--error' : ''}${item.group === null ? ' card--wide' : ''}`}>
      <span className={`tag tag--${item.kind}`}>{tagFor(item.kind)}</span>
      <h3>{item.title}</h3>
      <p className="mech">{item.mechanism}</p>
      {filled ? (
        <>
          <div className="badges">
            {badgesFor(run, runs).map((b, i) => (
              <span key={i} className={`badge${b.tone ? ` badge--${b.tone}` : ''}`}>{b.text}</span>
            ))}
          </div>
          {run.error ? (
            <div className="errtext">{run.error}</div>
          ) : (
            <pre className="out">{run.content || '— пустой ответ —'}</pre>
          )}
        </>
      ) : (
        <div className="runline">
          <span className="dot" />
          <span>{pendingLabel(phase)}</span>
        </div>
      )}
    </article>
  )
}

function downloadResults(run) {
  const runs = run.variants
    .map(v => run.runs[v.id])
    .filter(Boolean)
    .map(({ kind, ...rest }) => rest)
  const payload = {
    meta: { ...run.meta, generated_at: new Date().toLocaleString('ru-RU'), source: 'lab' },
    groups: run.groups,
    runs,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'lab-results.json'
  a.click()
  URL.revokeObjectURL(a.href)
}

export default function Results({ run, runCount, promptReady, onStop, onRerun }) {
  const { phase, variants, groups, runs, delivered, elapsed, error } = run
  const hasResults = phase !== 'idle'
  const finished = phase === 'done' || phase === 'stopped' || phase === 'failed'
  const baseline = variants.find(v => v.id === 'baseline')
  const groupKeys = ['format', 'length', 'stop'].filter(k => groups[k])

  const statusText = () => {
    if (phase === 'running') {
      return (
        <>
          выполнено <b>{delivered}</b> из <b>{variants.length}</b>
          {elapsed ? ` · ${elapsed}` : ''}
        </>
      )
    }
    if (phase === 'done') {
      return (
        <>
          готово: <b>{delivered}</b> из <b>{variants.length}</b> {plural(variants.length, ['прогона', 'прогонов', 'прогонов'])} · {elapsed}
        </>
      )
    }
    if (phase === 'stopped') return <>остановлено пользователем · выполнено <b>{delivered}</b></>
    if (phase === 'failed') return <>ошибка: {error || 'неизвестная ошибка'}</>
    return null
  }

  return (
    <>
      {hasResults && (
        <div className="statusbar on">
          <span id="status-text">{statusText()}</span>
          {phase === 'running' && (
            <button type="button" className="btn-ghost btn-ghost--danger" onClick={onStop}>
              Остановить
            </button>
          )}
        </div>
      )}

      <div id="results">
        {!hasResults && (
          <div className="empty-state">
            <p>
              {promptReady
                ? 'Здесь появятся ответы модели. Нажмите «Запустить» выше.'
                : 'Здесь появятся ответы модели. Введите промпт выше и нажмите «Запустить».'}
            </p>
          </div>
        )}

        {hasResults && baseline && (
          <ResultCard item={baseline} run={runs.baseline} runs={runs} phase={phase} />
        )}

        {hasResults && groupKeys.map(key => (
          <section className="section" style={{ padding: '40px 0 0' }} key={key}>
            <div className="sec-head">
              <h2>{groups[key].name}</h2>
            </div>
            <p className="sec-q">{groups[key].question}</p>
            <div className="grid">
              {variants.filter(v => v.group === key).map(v => (
                <ResultCard key={v.id} item={v} run={runs[v.id]} runs={runs} phase={phase} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {finished && (
        <div className="actions on">
          <button type="button" className="btn-ghost" onClick={() => downloadResults(run)}>
            Скачать results.json
          </button>
          <button type="button" className="btn-ghost" onClick={onRerun} disabled={!promptReady}>
            Запустить ещё раз
          </button>
          <span className="run-hint">
            {delivered} из {runCount} {plural(runCount, ['прогона', 'прогонов', 'прогонов'])} ·
            метрики и полные тексты — внутри карточек; JSON пригодится для отчёта.
          </span>
        </div>
      )}
    </>
  )
}
