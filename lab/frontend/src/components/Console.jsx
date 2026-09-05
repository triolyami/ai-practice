import { MODEL_NOTES } from '../lib/constants.js'
import { plural } from '../lib/format.js'

function bodyClass(enabled) {
  return enabled ? 'control-body' : 'control-body off'
}
function ControlFormat({ data, patch }) {
  return (
    <div className={bodyClass(data.enabled)}>
      <div>
        <label className="mini-label" htmlFor="format-instr">Инструкция, добавляемая к промпту (и в пару с response_format)</label>
        <textarea
          id="format-instr"
          className="textarea mono"
          rows={2}
          spellCheck={false}
          value={data.instruction}
          onChange={e => patch({ instruction: e.target.value })}
        />
      </div>
    </div>
  )
}

function ControlLength({ data, patch }) {
  return (
    <div className={bodyClass(data.enabled)}>
      <div className="field-grid">
        <div>
          <label className="mini-label" htmlFor="length-words">Слов в промпте</label>
          <input
            id="length-words"
            className="input input--num"
            type="number"
            min="1"
            max="1000"
            value={data.words}
            onChange={e => patch({ words: e.target.value })}
          />
        </div>
        <div>
          <label className="mini-label" htmlFor="length-template">Шаблон инструкции, {'{n}'} — число слов</label>
          <input
            id="length-template"
            className="input mono"
            type="text"
            spellCheck={false}
            value={data.template}
            onChange={e => patch({ template: e.target.value })}
          />
        </div>
        <div>
          <label className="mini-label" htmlFor="length-tokens">max_tokens на API</label>
          <input
            id="length-tokens"
            className="input input--num"
            type="number"
            min="1"
            max="8192"
            value={data.maxTokens}
            onChange={e => patch({ maxTokens: e.target.value })}
          />
        </div>
      </div>
    </div>
  )
}

function ControlStop({ data, patch }) {
  return (
    <div className={bodyClass(data.enabled)}>
      <div className="field-grid field-grid--two">
        <div>
          <label className="mini-label" htmlFor="stop-seq">stop-последовательность (\n, \t — как escape)</label>
          <input
            id="stop-seq"
            className="input mono"
            type="text"
            spellCheck={false}
            value={data.sequence}
            onChange={e => patch({ sequence: e.target.value })}
          />
        </div>
        <div>
          <label className="mini-label" htmlFor="stop-instr">Инструкция, добавляемая к промпту</label>
          <input
            id="stop-instr"
            className="input"
            type="text"
            spellCheck={false}
            value={data.instruction}
            onChange={e => patch({ instruction: e.target.value })}
          />
        </div>
      </div>
    </div>
  )
}

const CONTROLS = [
  { name: 'format', title: 'Формат ответа', sub: 'слова в промпте против response_format на API', Body: ControlFormat },
  { name: 'length', title: 'Длина ответа', sub: '«не более {n} слов» в промпте против max_tokens на API', Body: ControlLength },
  { name: 'stop', title: 'Условие завершения', sub: 'инструкция «остановись» в промпте против stop-последовательности на API', Body: ControlStop },
]

export default function Console({ config, setField, patchControl, runCount, running, promptReady, onRun }) {
  const model = config.model
  const note = MODEL_NOTES[model]
  const promptChars = config.prompt.length

  const pickModel = (m) => setField('model', m)

  return (
    <div className="console">
      <div className="field-label">
        <span>Промпт</span>
        <span>
          {promptChars ? `${promptChars} ${plural(promptChars, ['символ', 'символа', 'символов'])}` : ''}
        </span>
      </div>
      <textarea
        className={`textarea${promptReady ? '' : ' invalid'}`}
        id="prompt"
        spellCheck={false}
        value={config.prompt}
        onChange={e => setField('prompt', e.target.value)}
      />

      <div className="row-pair">
        <div className="seg" role="group" aria-label="Модель">
          {Object.keys(MODEL_NOTES).map(m => (
            <button
              key={m}
              type="button"
              className={model === m ? 'active' : ''}
              onClick={() => pickModel(m)}
            >
              {m}
            </button>
          ))}
        </div>
        <label className="temp-wrap">
          temperature
          <input
            type="number"
            min="0"
            max="1"
            step="0.1"
            value={config.temperature}
            onChange={e => setField('temperature', e.target.value)}
          />
        </label>
      </div>
      <p className={`model-note${note.warn ? ' model-note--warn' : ''}`}>{note.text}</p>

      <div className="controls">
        {CONTROLS.map(({ name, title, sub, Body }) => {
          const data = config.controls[name]
          return (
            <div className="control" key={name}>
              <div className="control-head">
                <label className="switch-wrap">
                  <input
                    type="checkbox"
                    className="switch"
                    checked={data.enabled}
                    onChange={e => patchControl(name, { enabled: e.target.checked })}
                  />
                  <span className="control-name">{title}</span>
                </label>
                <span className="control-sub">{sub}</span>
              </div>
              <Body data={data} patch={patch => patchControl(name, patch)} />
            </div>
          )
        })}
      </div>

      <div className="run-row">
        <button
          type="button"
          className="btn-primary"
          disabled={running || !promptReady}
          onClick={onRun}
        >
          {running
            ? 'Выполняется…'
            : `Запустить ${runCount} ${plural(runCount, ['прогон', 'прогона', 'прогонов'])}`}
        </button>
        <span className="run-hint">
          {promptReady
            ? `${runCount} ${plural(runCount, ['запрос', 'запроса', 'запросов'])} к Z.ai · ключ из .env · обычно 15–60 с`
            : 'введите текст промпта'}
        </span>
      </div>
    </div>
  )
}
