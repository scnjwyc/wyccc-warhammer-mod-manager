// Folder layout changes list organization independently of the MOD load order.
export const buildFolderGroups = (mods, folders, layout = [], filtered = false) => {
  const membership = new Map()
  for (const folder of folders) {
    for (const id of folder.mod_ids || []) if (!membership.has(id)) membership.set(id, folder)
  }
  const groups = []
  const folderGroups = new Map()
  for (const mod of mods) {
    const folder = membership.get(mod.id)
    if (!folder) {
      groups.push({ key: `mod:${mod.id}`, folder: null, mods: [mod] })
    } else {
      if (!folderGroups.has(folder.id)) {
        const group = { key: `folder:${folder.id}`, folder, mods: [] }
        folderGroups.set(folder.id, group)
        groups.push(group)
      }
      folderGroups.get(folder.id).mods.push(mod)
    }
  }
  if (!filtered) {
    for (const folder of folders) {
      if (!folderGroups.has(folder.id)) groups.push({ key: `folder:${folder.id}`, folder, mods: [] })
    }
  }
  // Only folder positions are restored. Ungrouped MODs keep the selected sort
  // order, including the actual load order in the enabled list.
  const savedKeys = new Set(layout)
  const restored = groups.filter(group => !group.folder || !savedKeys.has(group.key))
  const groupsByKey = new Map(groups.map(group => [group.key, group]))
  for (let index = layout.length - 1; index >= 0; index -= 1) {
    const group = groupsByKey.get(layout[index])
    if (!group?.folder) continue
    const nextKey = layout.slice(index + 1).find(key => restored.some(item => item.key === key))
    const nextIndex = restored.findIndex(item => item.key === nextKey)
    restored.splice(nextIndex < 0 ? restored.length : nextIndex, 0, group)
  }
  return restored
}

export const moveFolderLayout = (groups, previousLayout, move) => {
  const sourceKey = `folder:${move.folderId}`
  const source = groups.find(group => group.key === sourceKey)
  if (!source) return null
  const target = move.targetFolderId
    ? groups.find(group => group.key === `folder:${move.targetFolderId}`)
    : groups.find(group => group.mods.some(mod => mod.id === move.targetModId))
  if (target?.key === sourceKey) return null
  const keys = groups.map(group => group.key).filter(key => key !== sourceKey)
  let index = target ? keys.indexOf(target.key) : keys.length
  if (target && move.placement === 'after') index += 1
  keys.splice(index, 0, sourceKey)
  // Preserve positions of groups hidden by search or belonging to MODs that
  // are currently unavailable, so a filtered move cannot erase their layout.
  const visible = new Set(keys)
  const remaining = [...keys]
  const merged = previousLayout.map(key => visible.has(key) ? remaining.shift() : key)
  return [...new Set([...merged, ...remaining])]
}
