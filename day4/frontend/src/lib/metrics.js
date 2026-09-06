export function checkFacts(text, factChecks) {
  const low = (text || '').toLowerCase()
  return factChecks.map(f => ({ ...f, ok: low.includes(f.pattern) }))
}

function tokenSet(text) {
  return new Set(((text || '').toLowerCase().match(/[a-zа-яё0-9]+/g) || []))
}

export function jaccard(a, b) {
  const A = tokenSet(a)
  const B = tokenSet(b)
  if (!A.size && !B.size) return 1
  let inter = 0
  for (const x of A) if (B.has(x)) inter++
  return inter / (A.size + B.size - inter)
}

export function laneSummary(items) {
  const done = items.filter(r => r.status === 'done' && r.text)
  if (done.length < 2) return null
  let simSum = 0
  let pairs = 0
  for (let i = 0; i < done.length; i++) {
    for (let j = i + 1; j < done.length; j++) {
      simSum += jaccard(done[i].text, done[j].text)
      pairs++
    }
  }
  return {
    count: done.length,
    similarity: simSum / pairs,
    identical: done.every(r => r.text === done[0].text),
  }
}

export function diversityLabel(similarity) {
  if (similarity >= 0.9) return 'почти одинаковые'
  if (similarity >= 0.6) return 'похожи'
  if (similarity >= 0.35) return 'различаются'
  return 'совсем разные'
}
