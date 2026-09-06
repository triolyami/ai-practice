const KEY = 'day3-runs-v1'

export function loadState() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (!raw || typeof raw !== 'object') return null
    if (typeof raw.task !== 'string' || !raw.runs || typeof raw.runs !== 'object') return null
    return raw
  } catch {
    return null
  }
}

export function saveState(state) {
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {}
}

export function clearState() {
  try {
    localStorage.removeItem(KEY)
  } catch {}
}
