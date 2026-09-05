export const MODEL_NOTES = {
  'glm-4.6': {
    text: 'рассуждения отключены — ограничения действуют на видимый ответ',
    warn: false,
  },
  'glm-5.3': {
    text: 'всегда думает: max_tokens и stop могут сработать на скрытых рассуждениях, а видимый ответ придёт пустым (находка дня 2)',
    warn: true,
  },
}

export const DEFAULT_CONFIG = {
  prompt: 'Расскажи, как устроен интернет',
  model: 'glm-4.6',
  temperature: '0',
  controls: {
    format: {
      enabled: true,
      instruction:
        'Ответь строго валидным JSON без markdown-ограждений и пояснений: {"тема": "...", "суть": "кратко", "факты": ["..."]}',
    },
    length: {
      enabled: true,
      words: '30',
      maxTokens: '60',
      template: 'Ответь не более чем {n} словами.',
    },
    stop: {
      enabled: true,
      sequence: '\\n\\n',
      instruction: 'Заверши ответ после первого абзаца, не добавляя ничего после.',
    },
  },
}

export function buildPayload(config) {
  const { format, length, stop } = config.controls
  return {
    prompt: config.prompt,
    model: config.model,
    temperature: Math.max(0, Math.min(1, parseFloat(config.temperature) || 0)),
    controls: {
      format: { enabled: format.enabled, instruction: format.instruction },
      length: {
        enabled: length.enabled,
        words: parseInt(length.words, 10),
        max_tokens: parseInt(length.maxTokens, 10),
        template: length.template,
      },
      stop: {
        enabled: stop.enabled,
        sequence: stop.sequence,
        instruction: stop.instruction,
      },
    },
  }
}
