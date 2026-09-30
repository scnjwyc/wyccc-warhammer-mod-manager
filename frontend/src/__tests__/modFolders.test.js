import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import { useAppStore } from '../store'

const folder = { id: 'folder', name: 'UI', mod_ids: ['a'], collapsed_active: false, collapsed_inactive: true }
const payload = { game_id: 'warhammer3', playset_id: 'default', mod_folders: [folder] }

beforeEach(() => {
  setActivePinia(createPinia())
  invokeMock.mockReset()
  invokeMock.mockResolvedValue(payload)
})

describe('persistent MOD folder state', () => {
  it('saves folder actions without saving or changing the load order', async () => {
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3' }
    store.activeIds = ['b', 'a']
    await store.createModFolder('UI', ['a'])
    await store.assignModFolder(['a', 'c'], 'folder')
    await store.toggleModFolder('folder', 'inactive')
    await store.renameModFolder('folder', 'New name')
    await store.assignModFolder(['a'])
    await store.deleteModFolder('folder')
    expect(invokeMock.mock.calls).toEqual([
      ['create_mod_folder', 'UI', ['a'], 'warhammer3', 'default'],
      ['assign_mod_folder', ['a', 'c'], 'folder', 'warhammer3', 'default'],
      ['set_mod_folder_collapsed', 'folder', 'inactive', false, 'warhammer3', 'default'],
      ['rename_mod_folder', 'folder', 'New name', 'warhammer3', 'default'],
      ['assign_mod_folder', ['a'], '', 'warhammer3', 'default'],
      ['delete_mod_folder', 'folder', 'warhammer3', 'default'],
    ])
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(store.dirty).toBe(false)
  })

  it('loads folders with a playset and clears them when the game context is reset', () => {
    const store = useAppStore()
    store.applyPlaysetPayload({ current_playset: { id: 'other' }, mod_folders: [folder] })
    expect(store.modFolders).toEqual([folder])
    store.applyPlaysetPayload({ current_playset: { id: 'default' }, mod_folders: [] })
    expect(store.modFolders).toEqual([])
    store.modFolders = [folder]
    store.clearGameContextData()
    expect(store.modFolders).toEqual([])
  })

  it.each(['game', 'playset'])('ignores a late folder response after switching %s', async change => {
    let finish
    invokeMock.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3' }
    const pending = store.createModFolder('UI', ['a'])
    if (change === 'game') store.beginGameContextChange()
    else store.currentPlaysetId = 'other'
    finish(payload)
    await pending
    expect(store.modFolders).toEqual([])
  })

  it('preserves folders and surfaces a failed save', async () => {
    const store = useAppStore()
    store.modFolders = [folder]
    invokeMock.mockRejectedValue(new Error('Save failed'))
    await expect(store.deleteModFolder('folder')).rejects.toThrow('Save failed')
    expect(store.modFolders).toEqual([folder])
    expect(store.busy).toBe('')
    expect(store.toast.type).toBe('error')
  })

  it('ignores a stale folder snapshot from a background scan after a folder save', async () => {
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3' }
    vi.spyOn(store, 'loadPreview').mockResolvedValue()
    vi.spyOn(store, 'loadThumbnails').mockResolvedValue()
    const oldRevision = store.modFolderRevision
    await store.createModFolder('UI', ['a'])
    await store.applyExternalScan({ game_id: 'warhammer3', mods: [], mod_folders: [] }, { folderRevision: oldRevision })
    expect(store.modFolders).toEqual([folder])
  })
})
