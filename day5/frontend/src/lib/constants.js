export const DEFAULT_PROMPT = 'Расскажи, как устроен интернет'

export const MODELS = {
  'glm-4.5-flash': {
    label: 'glm-4.5-flash',
    tier: 'weak',
    tierName: 'Слабая',
    note: 'бесплатная; сама по умолчанию включает рассуждения, здесь они отключены',
    price: 'бесплатно',
  },
  'glm-4.6': {
    label: 'glm-4.6',
    tier: 'medium',
    tierName: 'Средняя',
    note: 'рассуждения отключены — $0.60 / $2.20 за 1M токенов',
    price: '$0.60 / $2.20',
  },
  'glm-5.3': {
    label: 'glm-5.3',
    tier: 'strong',
    tierName: 'Сильная',
    note: 'всегда думает (effort low) — $1.40 / $4.40 за 1M токенов',
    price: '$1.40 / $4.40',
  },
}

export const MAX_PARALLEL = 3
