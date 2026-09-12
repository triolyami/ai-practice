export const MODEL_NOTES = {
  'deepseek-v4-flash': {
    text: 'быстрая, рассуждает сама — текущий выбор по умолчанию',
    warn: false,
  },
  'deepseek-v4-pro': {
    text: 'старшая: отвечает глубже, но медленнее и дороже',
    warn: false,
  },
  'glm-4.6': {
    text: 'быстрая, рассуждения отключены — нужен баланс Z.ai',
    warn: false,
  },
  'glm-5.3': {
    text: 'всегда думает: глубже, но медленнее — нужен баланс Z.ai',
    warn: false,
  },
}

export const DEFAULT_AGENT = {
  name: '',
  systemPrompt: '',
  model: 'deepseek-v4-flash',
}

export function snapshot(settings) {
  return {
    name: settings.name.trim(),
    system_prompt: settings.systemPrompt.trim(),
    model: settings.model,
  }
}
