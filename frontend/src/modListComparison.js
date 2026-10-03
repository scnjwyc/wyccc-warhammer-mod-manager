const packKey = mod => String(mod.pack_name || '').toLowerCase()

export function compareModLists(snapshot, currentMods) {
  if (!snapshot.available) return { available: false }
  const previous = snapshot.mods || []
  const previousKeys = new Set(previous.map(packKey))
  const currentByKey = new Map(currentMods.map((mod, index) => [packKey(mod), { mod, index }]))
  const previousShared = previous.filter(mod => currentByKey.has(packKey(mod)))
  const currentShared = currentMods.filter(mod => previousKeys.has(packKey(mod)))
  const currentRanks = new Map(currentShared.map((mod, index) => [packKey(mod), index]))
  const previousRanks = new Map(previousShared.map((mod, index) => [packKey(mod), index]))
  const removed = []
  const shared = []
  previous.forEach((mod, index) => {
    const current = currentByKey.get(packKey(mod))
    const entry = { packName: mod.pack_name, mod: current?.mod || mod, previousPosition: index + 1 }
    if (!current) removed.push(entry)
    else shared.push({
      ...entry,
      currentPosition: current.index + 1,
      reordered: previousRanks.get(packKey(mod)) !== currentRanks.get(packKey(mod)),
    })
  })
  const added = currentMods.filter(mod => !previousKeys.has(packKey(mod)))
    .map(mod => ({ packName: mod.pack_name, mod }))
  const reorderedCount = shared.filter(item => item.reordered).length
  return {
    available: true, startedAt: snapshot.started_at, removed, added, shared, reorderedCount,
    recordId: snapshot.id || '',
    identical: !removed.length && !added.length && !reorderedCount,
  }
}
