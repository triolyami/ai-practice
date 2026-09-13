import { COMPRESSION_MODES, MODELS, MODEL_NOTES } from '../lib/constants.js'
import { plural } from '../lib/format.js'

export default function SettingsPanel({ settings, setSettings, onReset, canReset, busy, turns }) {
  const set = (name, value) => setSettings(prev => ({ ...prev, [name]: value }))
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
          <span className="set-name">Сжатие истории</span>
          <div className="seg seg--sm" role="group">
            {Object.entries(COMPRESSION_MODES).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                className={settings.compression === mode ? 'active' : ''}
                onClick={() => set('compression', mode)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="set-note">
          «без сжатия» — вся история уходит в каждый запрос целиком (как в днях 7–8);
          «скользящее» — сообщения старше последних 10 заменяются одной обновляемой сводкой;
          «по чанкам» — каждые 10 старых сообщений получают отдельную сводку.
          Сжатие выполняет та же модель после ответа; переключать можно в любой момент,
          счётчики расхода считаются отдельно по каждому режиму
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
          историю и сводки хранит сам агент, а не браузер: кнопка вызывает agent.reset() на сервере,
          вместе с ней обнуляются счётчики токенов и стоимости
        </p>
      </div>
    </div>
  )
}
