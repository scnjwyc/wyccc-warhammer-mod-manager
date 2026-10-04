import { describe, expect, it } from 'vitest'
import { buildFolderGroups, moveFolderLayout } from '../modFolderLayout'

const mods = ['a', 'b', 'c', 'd'].map(id => ({ id }))
const folders = [
  { id: 'one', mod_ids: ['a'] }, { id: 'two', mod_ids: ['c'] },
]
const keys = groups => groups.map(group => group.key)

describe('folder positions independent of MOD order', () => {
  it('moves a folder between ungrouped MODs and restores the layout', () => {
    const groups = buildFolderGroups(mods, folders)
    const layout = moveFolderLayout(groups, [], {
      folderId: 'one', targetModId: 'b', placement: 'after',
    })
    expect(keys(buildFolderGroups(mods, folders, layout)))
      .toEqual(['mod:b', 'folder:one', 'folder:two', 'mod:d'])
    expect(mods.map(mod => mod.id)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('keeps the selected MOD sort while anchoring the folder to its target', () => {
    const layout = ['mod:b', 'folder:one', 'mod:d', 'folder:two']
    const sortedMods = [mods[3], mods[1], mods[0], mods[2]]
    const groups = buildFolderGroups(sortedMods, folders, layout)
    expect(keys(groups)).toEqual(['folder:one', 'mod:d', 'mod:b', 'folder:two'])
    expect(groups.filter(group => !group.folder).flatMap(group => group.mods.map(mod => mod.id)))
      .toEqual(['d', 'b'])
  })

  it('retains hidden groups when moving during a search', () => {
    const oldLayout = ['mod:b', 'folder:one', 'mod:missing', 'folder:two', 'mod:d']
    const visible = buildFolderGroups([mods[0], mods[2]], folders, oldLayout, true)
    const next = moveFolderLayout(visible, oldLayout, {
      folderId: 'one', targetFolderId: 'two', placement: 'after',
    })
    expect(next).toEqual(['mod:b', 'folder:two', 'mod:missing', 'folder:one', 'mod:d'])
    expect(keys(buildFolderGroups(mods, folders, next)))
      .toEqual(['mod:b', 'folder:two', 'folder:one', 'mod:d'])
  })

  it('restores a moved folder when its anchor MOD is no longer visible', () => {
    expect(keys(buildFolderGroups([mods[0]], folders, ['mod:b', 'folder:one', 'mod:d', 'folder:two'])))
      .toEqual(['folder:one', 'folder:two'])
  })
})
