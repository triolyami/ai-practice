export default function JudgeCard({ judge, meta, judging, error, hasEnough, onJudge, busy }) {
  if (judging) {
    return (
      <section className="judge-card">
        <span className="side-title">Судья</span>
        <span className="runline">
          <span className="dot" /> судья glm-5.3 читает ответы вслепую…
        </span>
      </section>
    )
  }
  if (error) {
    return (
      <section className="judge-card">
        <span className="side-title">Судья</span>
        <p className="errtext">{error}</p>
      </section>
    )
  }
  if (judge) {
    return (
      <section className="judge-card">
        <div className="judge-head">
          <span className="side-title">Вердикт судьи</span>
          <span className="meta">
            {meta?.model || 'glm-5.3'} ·{' '}
            {meta?.latency_ms != null ? `${(meta.latency_ms / 1000).toFixed(1)} с` : '—'} ·{' '}
            {meta?.completion_tokens != null ? `${meta.completion_tokens} токенов` : '—'}
          </span>
        </div>
        <p className="judge-verdict">{judge.verdict}</p>
        <p className="task-note">
          ответы были обезличены (A/B/C, порядок перемешан), судья видел только время, токены и
          стоимость; близким по качеству ответам он предпочитает более дешёвый или быстрый
        </p>
      </section>
    )
  }
  return (
    <section className="judge-card">
      <div className="judge-head">
        <span className="side-title">Судья</span>
        <button
          type="button"
          className="btn btn--primary"
          disabled={!hasEnough || busy}
          onClick={onJudge}
        >
          спросить судью
        </button>
      </div>
      <p className="task-note">
        {hasEnough
          ? 'glm-5.3 оценит ответы вслепую: качество важнее, при равном качестве — цена и скорость'
          : 'нужно минимум два готовых ответа — судья сравнивает их между собой'}
      </p>
    </section>
  )
}
