import { COMPRESSION_MODES } from '../lib/constants.js'
import { plural } from '../lib/format.js'

export default function SummaryPanel({ summaries, compression }) {
  const rolling = summaries?.rolling ?? { text: null, covered: 0 }
  const chunks = summaries?.chunks ?? { texts: [], covered: 0 }
  const active = compression === 'chunks' ? chunks : rolling
  const covered = compression === 'chunks' ? chunks.covered : rolling.covered
  const hasContent = compression === 'chunks' ? chunks.texts.length > 0 : !!rolling.text

  return (
    <section className="ctx-panel">
      <span className="mini-label">что помнит агент</span>
      <div className="sum-modes">
        {Object.entries(COMPRESSION_MODES).map(([mode, label]) => {
          const on = mode === compression
          return (
            <span key={mode} className={`sum-mode${on ? ' sum-mode--on' : ''}`}>
              {label}
            </span>
          )
        })}
      </div>
      {hasContent ? (
        <details className="sum-details" open>
          <summary>
            сжато {covered} {plural(covered, ['сообщение', 'сообщения', 'сообщений'])}
            {compression === 'chunks' && ` · ${chunks.texts.length} ${plural(chunks.texts.length, ['период', 'периода', 'периодов'])}`}
          </summary>
          {compression === 'chunks' ? (
            <div className="out sum-out">
              {chunks.texts.map((text, i) => (
                <p key={i}><b>Период {i + 1}.</b> {text}</p>
              ))}
            </div>
          ) : (
            <div className="out sum-out">{rolling.text}</div>
          )}
        </details>
      ) : (
        <p className="sum-empty">
          сводки ещё нет — старые сообщения начнут сжиматься, когда накопится история
        </p>
      )}
    </section>
  )
}
