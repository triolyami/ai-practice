import { MODELS, MODEL_NOTES, LAYERS, LAYER_ORDER } from '../lib/constants.js'
import { plural } from '../lib/format.js'

export default function SettingsPanel({ settings, setSettings, onReset, canReset, busy, turns }) {
  const set = (name, value) => setSettings(prev => ({ ...prev, [name]: value }))
  const setLayer = (key, value) =>
    setSettings(prev => ({ ...prev, layers: { ...prev.layers, [key]: value } }))
  const spec = MODELS[settings.model]

  return (
    <div className="settings">
      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Имя агента</span>
        </div>
        <div className="set-fields">
          <input
            type="text"
            className="input input--sm"
            value={settings.name}
            maxLength={60}
            placeholder="Ассистент"
            onChange={e => set('name', e.target.value)}
          />
        </div>
        <p className="set-note">
          пусто — будет «Ассистент»; имя входит в системный промпт по умолчанию
        </p>
      </div>

      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Системный промпт</span>
        </div>
        <div className="set-fields" style={{ width: '100%' }}>
          <textarea
            className="input prompt-input"
            rows={3}
            value={settings.systemPrompt}
            placeholder="пусто — по умолчанию: дружелюбный ассистент, кратко и по делу"
            onChange={e => set('systemPrompt', e.target.value)}
          />
        </div>
        <p className="set-note">
          промпт агента идёт первым, блок профиля — после него: при конфликте профиль важнее;
          применяется к экземпляру агента на сервере сразу — накопленная память диалога сохраняется
        </p>
      </div>

      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Модель</span>
          <div className="seg seg--sm" role="group">
            {Object.keys(MODEL_NOTES).map(m => (
              <button
                key={m}
                type="button"
                className={settings.model === m ? 'active' : ''}
                onClick={() => set('model', m)}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        <p className={`set-note${spec.warn ? ' set-note--warn' : ''}`}>
          {spec.note} · контекст {spec.context_limit.toLocaleString('ru-RU')} токенов ·
          ${spec.price_in.toFixed(2)} / ${spec.price_out.toFixed(2)} за 1M (вход/выход)
        </p>
      </div>

      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Слои в запросе</span>
        </div>
        <div className="set-fields set-fields--inline">
          {LAYER_ORDER.map(key => (
            <label key={key} className="layer-check">
              <input
                type="checkbox"
                checked={settings.layers?.[key] !== false}
                onChange={e => setLayer(key, e.target.checked)}
              />
              {LAYERS[key]}
            </label>
          ))}
        </div>
        <p className="set-note">
          какие слои уходят в следующий запрос: выключите слой, чтобы увидеть,
          как ответ меняется без него (профиль off = привязка остаётся, но блок не уходит —
          быстрый A/B внутри одного чата)
        </p>
      </div>

      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Память</span>
          <div className="set-mid">
            <span className="mini-label">
              {turns} {plural(turns, ['реплика', 'реплики', 'реплик'])}
            </span>
            <button
              type="button"
              className="btn-danger"
              disabled={!canReset || busy}
              onClick={onReset}
              title={canReset ? 'Вызывает agent.reset() на сервере' : 'Сначала начните диалог'}
            >
              сбросить диалог
            </button>
          </div>
        </div>
        <p className="set-note">
          историю хранит сам агент, а не браузер: кнопка вызывает agent.reset() на сервере —
          чистятся краткосрочная память и счётчики; профили и longterm.md не затрагиваются
        </p>
      </div>
    </div>
  )
}
