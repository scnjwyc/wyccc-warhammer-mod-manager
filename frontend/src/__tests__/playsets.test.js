// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('../bridge', () => ({ invoke: invokeMock }))

import { useAppStore } from '../store'

const defaultPlayset = {
  id: 'default',
  name: '默认',
  is_default: true,
  mod_ids: ['a', 'b'],
}

describe('playset state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    invokeMock.mockReset()
  })

  it('persists the configured MOD type order', async () => {
    invokeMock.mockResolvedValue({
      items: [
        { id: 'custom:audio', name: '音效', built_in: false },
        { id: 'ui', name: 'UI', built_in: true },
      ],
    })
    const store = useAppStore()
    store.modTypes = [
      { id: 'ui', name: 'UI', built_in: true },
      { id: 'custom:audio', name: '音效', built_in: false },
    ]

    await store.reorderModTypes(['custom:audio', 'ui'])

    expect(invokeMock).toHaveBeenCalledWith('reorder_mod_types', ['custom:audio', 'ui'])
    expect(store.modTypes.map(item => item.id)).toEqual(['custom:audio', 'ui'])
  })

  it('persists rapid enable and reorder operations to the current playset in order', async () => {
    let saveCount = 0
    invokeMock.mockImplementation(async (method, playsetId, modIds) => {
      if (method === 'save_load_order') {
        saveCount += 1
        return { order_token: `token-${saveCount}`, backup: null }
      }
      expect(method).toBe('update_playset')
      return {
        playset: { ...defaultPlayset, mod_ids: [...modIds] },
        playsets: [{ ...defaultPlayset, mod_ids: [...modIds] }],
        current_playset: { ...defaultPlayset, mod_ids: [...modIds] },
      }
    })
    const store = useAppStore()
    store.playsets = [defaultPlayset]
    store.currentPlaysetId = 'default'
    store.activeIds = ['a', 'b']
    store.mods = [
      { id: 'a', pack_name: 'a.pack' },
      { id: 'b', pack_name: 'b.pack' },
      { id: 'c', pack_name: 'c.pack' },
    ]

    store.enable('c')
    store.reorder('c', 'a')
    await store.flushPlaysetUpdates()

    expect(store.activeIds).toEqual(['c', 'a', 'b'])
    expect(invokeMock.mock.calls).toEqual([
      ['update_playset', 'default', ['a', 'b', 'c']],
      ['save_load_order', ['a', 'b', 'c'], 'missing'],
      ['update_playset', 'default', ['c', 'a', 'b']],
      ['save_load_order', ['c', 'a', 'b'], 'token-1'],
    ])
    expect(store.dirty).toBe(false)
  })

  it('flushes current changes before switching and loads the selected playset', async () => {
    const other = {
      id: 'other',
      name: '战役',
      is_default: false,
      mod_ids: ['b'],
    }
    invokeMock.mockImplementation(async method => {
      if (method === 'update_playset') {
        return {
          playset: { ...defaultPlayset, mod_ids: ['a'] },
          playsets: [{ ...defaultPlayset, mod_ids: ['a'] }, other],
          current_playset: { ...defaultPlayset, mod_ids: ['a'] },
        }
      }
      if (method === 'switch_playset') {
        return {
          playsets: [defaultPlayset, other],
          current_playset: other,
          ordered_mod_ids: ['b'],
          missing_mod_ids: [],
        }
      }
      if (method === 'save_load_order') {
        return { order_token: 'saved-token', backup: null }
      }
      throw new Error(`unexpected method: ${method}`)
    })
    const store = useAppStore()
    store.playsets = [defaultPlayset, other]
    store.currentPlaysetId = 'default'
    store.activeIds = ['a', 'b']

    store.disable('b')
    await store.switchPlayset('other')
    await store.flushPlaysetUpdates()

    expect(invokeMock.mock.calls.map(call => call[0])).toEqual([
      'update_playset',
      'save_load_order',
      'switch_playset',
      'update_playset',
      'save_load_order',
    ])
    expect(store.currentPlaysetId).toBe('other')
    expect(store.activeIds).toEqual(['b'])
    expect(store.dirty).toBe(false)
  })

  it('imports directly into the current playset and clears its previous missing entries', async () => {
    const imported = {
      ...defaultPlayset,
      mod_ids: ['b'],
    }
    invokeMock.mockImplementation(async method => {
      if (method === 'import_share') {
        return {
          playsets: [imported],
          current_playset: imported,
          ordered_mod_ids: ['b'],
          missing_mod_ids: [],
          missing: [],
        }
      }
      if (method === 'update_playset') {
        return { playsets: [imported], current_playset: imported }
      }
      if (method === 'save_load_order') {
        return { order_token: 'saved-token', backup: null }
      }
      throw new Error(`unexpected method: ${method}`)
    })
    const store = useAppStore()
    store.playsets = [defaultPlayset]
    store.currentPlaysetId = 'default'
    store.activeIds = ['a']
    store.missingEnabledIds = ['not-installed']

    await store.importShare('share-code')
    await store.flushPlaysetUpdates()

    expect(invokeMock).toHaveBeenCalledWith('import_share', 'share-code')
    expect(store.currentPlaysetId).toBe('default')
    expect(store.activeIds).toEqual(['b'])
    expect(store.missingEnabledIds).toEqual([])
    expect(store.dirty).toBe(false)
    expect(invokeMock.mock.calls.map(call => call[0])).toEqual([
      'import_share',
      'update_playset',
      'save_load_order',
    ])
  })

  it('keeps pending Workshop entries in their imported position while active mods move', () => {
    const store = useAppStore()
    const pending = 'pending:steam:123:shared.pack'
    store.playsets = [{ ...defaultPlayset, mod_ids: ['a', pending, 'b'] }]
    store.currentPlaysetId = 'default'
    store.activeIds = ['b', 'a']
    store.missingEnabledIds = [pending]

    expect(store.playsetOrderSnapshot()).toEqual(['b', pending, 'a'])
  })

  it('activates each downloaded collection MOD in its reserved collection position', async () => {
    const pending = 'pending:steam:456:'
    invokeMock.mockImplementation(async method => {
      expect(method).toBe('scan_mods')
      return {
        mods: [
          { id: 'installed-id', pack_name: 'installed.pack' },
          { id: 'downloaded-id', pack_name: 'downloaded.pack', workshop_id: '456' },
        ],
        enabled_order: ['installed-id', 'downloaded-id'],
        missing_enabled_ids: [],
        order_token: 'fresh-token',
        warnings: [],
        playsets: [{ ...defaultPlayset, mod_ids: ['installed-id', 'downloaded-id'] }],
        current_playset: { ...defaultPlayset, mod_ids: ['installed-id', 'downloaded-id'] },
      }
    })
    const store = useAppStore()
    store.playsets = [{ ...defaultPlayset, mod_ids: ['installed-id', pending] }]
    store.currentPlaysetId = 'default'
    store.activeIds = ['installed-id']
    store.missingEnabledIds = [pending]
    store.dirty = true
    store.collectionImportSync = { playsetId: 'default', pendingWorkshopIds: ['456'] }
    store.recordCurrentPlaysetChange = vi.fn(() => Promise.resolve())

    await store.refreshCollectionImportDownloads()

    expect(store.activeIds).toEqual(['installed-id', 'downloaded-id'])
    expect(store.missingEnabledIds).toEqual([])
    expect(store.collectionImportSync).toBeNull()
    expect(store.recordCurrentPlaysetChange).toHaveBeenCalledOnce()
  })

  it('reorders a batch as one group while preserving the selected order', () => {
    const store = useAppStore()
    store.activeIds = ['a', 'b', 'c', 'd', 'e']
    store.recordCurrentPlaysetChange = vi.fn()

    store.reorderMany(['b', 'c'], 'e', 'b')
    expect(store.activeIds).toEqual(['a', 'd', 'e', 'b', 'c'])

    store.reorderMany(['b', 'c'], 'a', 'c')
    expect(store.activeIds).toEqual(['b', 'c', 'a', 'd', 'e'])

    store.reorderMany(['b', 'c'], 'b', 'b')
    expect(store.activeIds).toEqual(['b', 'c', 'a', 'd', 'e'])
    expect(store.recordCurrentPlaysetChange).toHaveBeenCalledTimes(2)
  })

  it('previews share subscriptions and forwards accepted bulk subscriptions', async () => {
    invokeMock.mockImplementation(async (method, value) => {
      if (method === 'preview_import_share') {
        return { unsubscribed: [{ workshop_id: '123', title: 'Missing Mod' }] }
      }
      if (method === 'subscribe_workshop_items') {
        return { subscribed: value, already_subscribed: [] }
      }
      throw new Error(`unexpected method: ${method}`)
    })
    const store = useAppStore()

    const preview = await store.previewShareImport('share-code')
    const subscribed = await store.subscribeWorkshopItems(['123'])

    expect(preview.unsubscribed[0].workshop_id).toBe('123')
    expect(subscribed.subscribed).toEqual(['123'])
    expect(invokeMock.mock.calls).toEqual([
      ['preview_import_share', 'share-code'],
      ['subscribe_workshop_items', ['123']],
    ])
  })
})
