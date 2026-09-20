import { STRATEGY_MODES } from '../lib/constants.js'
import { plural } from '../lib/format.js'

export default function FactsPanel({ facts, strategy }) {
  const pairs = facts?.pairs ?? []
  const covered = facts?.covered ?? 0

  return (
    <section className="ctx-panel">
      <span className="mini-label">что помнит агент</span>
      <div className="sum-modes">
        {Object.entries(STRATEGY_MODES).map(([mode, label]) => (
          <span key={mode} className={`sum-mode${mode === strategy ? ' sum-mode--on' : ''}`}>
            {label}
          </span>
        ))}
      </div>
      {strategy === 'facts' ? (
        pairs.length > 0 ? (
          <details className="sum-details" open>
            <summary>
              фактов: {pairs.length} · учтено {covered}{' '}
              {plural(covered, ['сообщение', 'сообщения', 'сообщений'])}
            </summary>
            <dl className="facts-list">
              {pairs.map(([key, value]) => (
                <div key={key} className="facts-row">
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </details>
        ) : (
          <p className="sum-empty">
            фактов ещё нет — после каждого ответа модель будет обновлять блок «ключ: значение»
          </p>
        )
      ) : strategy === 'window' ? (
        <p className="sum-empty">
          старые сообщения просто отбрасываются: модель видит только последние N —
          блок памяти у этой стратегии отсутствует
        </p>
      ) : (
        <p className="sum-empty">
          история хранится целиком — разгрузка контекста делается кнопкой
          «⤵ ветка отсюда» у сообщения
        </p>
      )}
    </section>
  )
}
