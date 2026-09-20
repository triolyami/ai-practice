import { LAYERS, fmtTokens } from '../lib/constants.js'
import { plural } from '../lib/format.js'

export const SEGMENTS = [
  { key: 'system', label: 'система', color: '#787774' },
  { key: 'longterm', label: 'долговременная', color: '#5B4A9F' },
  { key: 'profile', label: 'профиль', color: '#1F6C9F' },
  { key: 'history', label: 'история', color: '#346538' },
  { key: 'request', label: 'запрос', color: '#956400' },
]

function barParts(source) {
  const t = source.tokens || source
  return SEGMENTS.map(s => ({ ...s, value: t[s.key] ?? 0 }))
}

function layerNote(layers) {
  if (!layers) return null
  const off = Object.entries(LAYERS).filter(([k]) => layers[k] === false).map(([, v]) => v)
  if (!off.length) return null
  return `выключены: ${off.join(', ')}`
}

function StackedBar({ parts, fill, height }) {
  const sum = parts.reduce((s, p) => s + p.value, 0)
  return (
    <span className="ctx-bar" style={{ height }}>
      {sum > 0 && parts.map(p => p.value > 0 && (
        <span
          key={p.key}
          style={{ width: `${Math.max((p.value / sum) * fill, 0.8)}%`, background: p.color }}
          title={`${p.label}: ≈${fmtTokens(p.value)} токенов (оценка)`}
        />
      ))}
    </span>
  )
}

export default function ContextDiagram({ preview, metas }) {
  const turns = metas.map((m, i) => ({
    i,
    layers: m.layers,
    parts: barParts(m),
    total: m.tokens.total_with_answer ?? m.tokens.total_est,
    actual: m.tokens.total_with_answer != null,
  }))
  const shown = turns.slice(-30)
  const nextParts = preview ? barParts(preview) : null
  const max = Math.max(
    ...turns.map(t => t.total),
    ...(preview ? [preview.total] : []),
    1,
  )

  return (
    <section className="ctx-panel">
      <span className="mini-label">карта контекста</span>
      <div className="ctx-legend">
        {SEGMENTS.map(s => (
          <span key={s.key}>
            <i className="ctx-dot" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>

      {preview && (
        <div className="ctx-next" title="оценка состава запроса, который уйдёт при следующем ходе">
          <div className="ctx-next-head">
            <span>
              следующий запрос
              {preview.profile_name ? ` · ${preview.profile_name}` : ''}
              {preview.profile_missing ? ' · профиль не найден' : ''}
            </span>
            <span className="ctx-next-total">≈{fmtTokens(preview.total)}</span>
          </div>
          <StackedBar parts={nextParts} fill={(preview.total / max) * 100} height={16} />
          <span className="ctx-next-sub">
            {`истории ${preview.history_len} ${plural(preview.history_len, ['сообщение', 'сообщения', 'сообщений'])}`}
            {preview.pipeline?.length
              ? ` · пайплайн ${preview.pipeline.length} ${plural(preview.pipeline.length, ['шаг', 'шага', 'шагов'])}: ${preview.pipeline.join(' → ')}`
              : ''}
            {layerNote(preview.layers) ? ` · ${layerNote(preview.layers)}` : ' · все слои включены'}
          </span>
        </div>
      )}

      <div className="ctx-list">
        {shown.length === 0 && (
          <p className="ctx-empty">пока пусто — отправьте сообщение, и здесь появится, как менялся контекст по ходам</p>
        )}
          {[...shown].reverse().map(t => (
            <div key={t.i} className="ctx-row">
              <span
                className="ctx-turn"
                title={layerNote(t.layers) || 'все слои включены'}
              >
                {t.i + 1}
              </span>
              <StackedBar parts={t.parts} fill={(t.total / max) * 100} height={10} />
              <span
                className="ctx-total"
                title={t.actual
                  ? 'размер диалога после этого хода: промпт + текст ответа без скрытых рассуждений (факт API)'
                  : 'оценка: ход сделан до того, как счётчики стали считать по факту'}
              >
                {t.actual ? '' : '≈'}{fmtTokens(t.total)}
              </span>
            </div>
          ))}
      </div>
      {turns.length > shown.length && (
        <span className="ctx-more">показаны последние {shown.length} из {turns.length} ходов</span>
      )}
    </section>
  )
}
