import { FORMAT_INSTRUCTIONS, FORMAT_KINDS, MODEL_NOTES, VIAS, VIA_LABELS } from '../lib/constants.js'

function Seg({ options, value, onChange, disabledIds = [] }) {
  return (
    <div className="seg seg--sm" role="group">
      {options.map(o => (
        <button
          key={o}
          type="button"
          disabled={disabledIds.includes(o)}
          className={value === o ? 'active' : ''}
          onClick={() => onChange(o)}
        >
          {VIA_LABELS[o]}
        </button>
      ))}
    </div>
  )
}

export default function SettingsPanel({ settings, setSettings }) {
  const set = (name, value) => setSettings(prev => ({ ...prev, [name]: value }))
  const setControl = (name, patch) =>
    setSettings(prev => ({ ...prev, [name]: { ...prev[name], ...patch } }))

  const pickFormatKind = (kind) => {
    const downgrade = kind !== 'json' && settings.format.via === 'api'
    setControl('format', { kind, via: downgrade ? 'prompt' : settings.format.via })
  }

  return (
    <div className="settings">
      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Модель</span>
          <div className="set-mid">
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
        </div>
        <div className="set-mid" style={{ marginTop: '8px' }}>
          <label className="temp-wrap">
            temperature
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              value={settings.temperature}
              onChange={e => set('temperature', e.target.value)}
            />
          </label>
        </div>
        <p className={`set-note${MODEL_NOTES[settings.model].warn ? ' set-note--warn' : ''}`}>
          {MODEL_NOTES[settings.model].text}
        </p>
      </div>

      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Формат ответа</span>
          <Seg
            options={VIAS}
            value={settings.format.via}
            disabledIds={settings.format.kind === 'json' ? [] : ['api']}
            onChange={v => setControl('format', { via: v })}
          />
        </div>
        <div className="set-mid" style={{ marginTop: '8px' }}>
          <select
            className="input input--sm"
            value={settings.format.kind}
            onChange={e => pickFormatKind(e.target.value)}
            aria-label="Формат"
          >
            {Object.entries(FORMAT_KINDS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>
        {settings.format.via === 'prompt' && (
          <p className="set-note">к промпту добавится: «{FORMAT_INSTRUCTIONS[settings.format.kind]}»</p>
        )}
        {settings.format.via === 'api' && (
          <p className="set-note">на API: response_format: {'{type: json_object}'} — парсируемый JSON гарантирует сервер</p>
        )}
      </div>

      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Длина ответа</span>
          <Seg options={VIAS} value={settings.length.via} onChange={v => setControl('length', { via: v })} />
        </div>
        {settings.length.via !== 'off' && (
          <div className="set-fields">
            {settings.length.via === 'prompt' && (
              <label className="set-field">
                <span className="mini-label">слов в промпте</span>
                <input
                  type="number"
                  min="1"
                  max="1000"
                  className="input input--sm"
                  value={settings.length.words}
                  onChange={e => setControl('length', { words: e.target.value })}
                />
              </label>
            )}
            {settings.length.via === 'api' && (
              <label className="set-field">
                <span className="mini-label">max_tokens на API</span>
                <input
                  type="number"
                  min="1"
                  max="8192"
                  className="input input--sm"
                  value={settings.length.maxTokens}
                  onChange={e => setControl('length', { maxTokens: e.target.value })}
                />
              </label>
            )}
            {settings.length.via === 'prompt' && (
              <p className="set-note">к промпту добавится: «Ответь не более чем {settings.length.words} словами.»</p>
            )}
          </div>
        )}
      </div>

      <div className="set-row">
        <div className="set-head">
          <span className="set-name">Условие завершения</span>
          <Seg options={VIAS} value={settings.stop.via} onChange={v => setControl('stop', { via: v })} />
        </div>
        {settings.stop.via !== 'off' && (
          <div className="set-fields">
            <label className="set-field set-field--wide">
              <span className="mini-label">последовательность (\n, \t — как escape)</span>
              <input
                type="text"
                className="input input--sm mono"
                spellCheck={false}
                value={settings.stop.sequence}
                onChange={e => setControl('stop', { sequence: e.target.value })}
              />
            </label>
            {settings.stop.via === 'api' && (
              <p className="set-note">на API: stop: [«{settings.stop.sequence}»] — генерация обрывается на первом вхождении</p>
            )}
            {settings.stop.via === 'prompt' && (
              <p className="set-note">в промпт добавится просьба закончить непосредственно перед «{settings.stop.sequence}»</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
