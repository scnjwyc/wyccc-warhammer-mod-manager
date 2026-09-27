import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { applyInterfaceLanguage, hasTranslation, localizeBackendMessage } from '../languages'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import { useAppStore } from '../store'

const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const scanPayload = (game, id) => ({
  game_id: game, mods: [{ id, pack_name: `${id}.pack`, source: 'data' }],
  enabled_order: [id], missing_enabled_ids: [], warnings: [],
  order_token: id, playsets: [{ id: `${game}-playset` }],
  current_playset: { id: `${game}-playset` },
})

beforeEach(() => {
  setActivePinia(createPinia())
  invokeMock.mockReset()
})
afterEach(() => {
  useAppStore().stopCollectionImportDownloadSync()
  applyInterfaceLanguage('zh-CN')
})

it.each(['refreshWorkshopInBackground', 'refreshModsInBackground', 'refreshCollectionImportDownloads'])(
  'discards old game results from %s even after switching away and back', async method => {
    const oldScan = deferred()
    const started = deferred()
    invokeMock.mockImplementation((name, changes) => {
      if (name === 'scan_mods') { started.resolve(); return oldScan.promise }
      if (name === 'save_settings') return Promise.resolve({
        settings: { selected_game: changes.selected_game, language: 'zh-CN' },
        paths: { game_id: changes.selected_game }, path_health: {},
      })
      if (name === 'get_changelog') return Promise.resolve({ items: [] })
      return Promise.resolve({})
    })
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3', fetch_workshop_metadata: false }
    store.collectionImportSync = { playsetId: store.currentPlaysetId, pendingWorkshopIds: ['123'] }
    vi.spyOn(store, 'loadPreview').mockResolvedValue()
    vi.spyOn(store, 'loadThumbnails').mockResolvedValue()
    vi.spyOn(store, 'refreshWorkshopUpdateEligibility').mockResolvedValue()
    const pending = store[method]()
    await started.promise
    await store.saveSettings({ selected_game: 'three_kingdoms' })
    expect(store.collectionImportSync).toBeNull()
    await store.saveSettings({ selected_game: 'warhammer3' })
    await store.applyExternalScan(scanPayload('warhammer3', 'new'))
    oldScan.resolve(scanPayload('warhammer3', 'old'))
    await pending
    expect(store.mods.map(mod => mod.id)).toEqual(['new'])
    expect(store.activeIds).toEqual(['new'])
    expect(store.orderToken).toBe('new')
  },
)

it('discards foreground scans explicitly marked obsolete by the backend', async () => {
  const store = useAppStore()
  store.settings.selected_game = 'warhammer3'
  store.mods = [{ id: 'current' }]
  invokeMock.mockResolvedValue({ discarded: true, game_id: 'warhammer3' })
  expect(await store.scan()).toBeNull()
  expect(store.mods).toEqual([{ id: 'current' }])
})

it.each(['loadThumbnails', 'loadPreview', 'refreshRuntime'])(
  'does not apply delayed %s output after a path or game change', async method => {
    const response = deferred()
    invokeMock.mockReturnValue(response.promise)
    const store = useAppStore()
    store.mods = [{ id: 'same-id' }]
    store.selectedId = 'same-id'
    const pending = store[method]('same-id')
    store.beginGameContextChange()
    store.thumbnails = { 'same-id': 'new-thumbnail' }
    store.selectedPreview = 'new-preview'
    store.runtime = { running: true, mod_revision: 99 }
    response.resolve({ items: { 'same-id': 'old-thumbnail' }, url: 'old-preview', running: false, mod_revision: 1 })
    await pending
    expect(store.thumbnails['same-id']).toBe('new-thumbnail')
    expect(store.selectedPreview).toBe('new-preview')
    expect(store.runtime).toEqual({ running: true, mod_revision: 99 })
  },
)

it('clears old game state on automatic path detection', async () => {
  const store = useAppStore()
  store.mods = [{ id: 'old' }]
  store.playsets = [{ id: 'old-playset' }]
  store.missingEnabledIds = ['missing-old']
  store.selectedPreview = 'old-preview'
  invokeMock.mockResolvedValue({
    settings: { selected_game: 'three_kingdoms', language: 'zh-CN' }, paths: {}, found: true,
  })
  await store.detectPaths('three_kingdoms')
  expect(store.mods).toEqual([])
  expect(store.playsets).toEqual([])
  expect(store.missingEnabledIds).toEqual([])
  expect(store.selectedPreview).toBe('')
})

it('explains isolation and conflict failures in all six languages', () => {
  for (const language of ['zh-CN', 'en-US', 'ko-KR', 'ru-RU', 'ja-JP', 'es-ES']) {
    applyInterfaceLanguage(language)
    for (const key of ['share.wrongGame', 'share.legacyGame', 'warnings.duplicatePack', 'errors.duplicatePack', 'errors.packIndex', 'errors.encryptedPack']) {
      expect(hasTranslation(key)).toBe(true)
    }
    expect(localizeBackendMessage('不能同时启用多个同名 Pack：same.pack')).toContain('same.pack')
    expect(localizeBackendMessage('不支持加密 Pack 索引：same.pack')).toContain('same.pack')
  }
})
