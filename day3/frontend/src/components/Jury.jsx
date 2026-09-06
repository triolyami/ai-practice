export default function Jury({ judge, onJudge, candidates, busy, task }) {
  const disabled = busy || candidates.length < 2
  const stale = judge?.status === 'done' && judge.task.trim() !== task.trim()
  return (
    <div className="jury">
      <div className="jury-head">
        <span className="side-title">вердикт жюри</span>
        <button
          type="button"
          className="chip-btn"
          disabled={disabled}
          onClick={onJudge}
          title={
            candidates.length < 2
              ? 'нужно хотя бы два завершённых ответа'
              : `собрать все завершённые ответы (${candidates.length}) и оценить их`
          }
        >
          оценить ответы{candidates.length >= 2 ? ` (${candidates.length})` : ''}
        </button>
      </div>
      {candidates.length < 2 && (
        <p className="compare-note">для вердикта жюри нужно хотя бы два завершённых ответа.</p>
      )}
      {judge?.status === 'running' && (
        <p className="runline">
          <span className="dot" />жюри читает ответы…
        </p>
      )}
      {judge?.status === 'error' && <p className="errtext">{judge.error}</p>}
      {judge?.status === 'done' && (
        <>
          {stale && (
            <p className="compare-note">задача изменилась после оценки — вердикт может быть неактуален.</p>
          )}
          {judge.result.verdict && <p className="compare-concl">{judge.result.verdict}</p>}
          <ol className="jury-list">
            {judge.result.ranking.map((r, i) => {
              const name = candidates.find(c => c.id === r.id)?.name || r.id
              return (
                <li key={r.id} className="jury-item">
                  <span className="jury-place">{i + 1}</span>
                  <div className="jury-body">
                    <div className="jury-line">
                      <span className="jury-name">{name}</span>
                      {r.id === judge.result.best && <span className="badge badge--ok">лучший</span>}
                      {r.correct === true && <span className="badge badge--ok">верно</span>}
                      {r.correct === false && <span className="badge badge--no">неверно</span>}
                      <span className="jury-score">{r.score != null ? `${r.score}/10` : '—'}</span>
                    </div>
                    {r.comment && <div className="jury-comment">{r.comment}</div>}
                  </div>
                </li>
              )
            })}
          </ol>
        </>
      )}
    </div>
  )
}
