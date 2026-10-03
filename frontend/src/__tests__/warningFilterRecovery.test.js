import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))

import App from '../App.vue'
import { useAppStore } from '../store'

describe('warning filter recovery through the MOD lists', () => {
  let wrapper
  let store
  let pinia

  const mod = (id, warnings = []) => ({
    id,
    pack_name: `${id}.pack`,
    effective_name: id,
    source: 'data',
    pack_type: 'mod',
    warnings,
  })
  const rowNames = panel => panel.findAll('.row-title').map(row => row.text())

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useAppStore()
    store.pathHealth = { game_ready: true }
    store.settings = { selected_game: 'warhammer3' }
    store.playsets = [{ id: 'default', mod_ids: ['broken', 'healthy'] }]
    store.mods = [
      mod('broken', [{ code: 'missing_dependency', message: '缺少依赖：base.pack' }]),
      mod('healthy'),
      mod('available'),
    ]
    store.activeIds = ['broken', 'healthy']
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    invokeMock.mockReset()
    invokeMock.mockImplementation(async (method, ...args) => {
      if (method === 'update_playset') return { missing_dependency_warnings: {} }
      if (method === 'save_load_order') return { order_token: 'saved', ordered_mod_ids: args[0] }
      if (method === 'get_diagnostics_history') return []
      return {}
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    vi.restoreAllMocks()
  })

  it('restores both lists after right-click filtering and disabling the last warning MOD', async () => {
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const active = wrapper.get('.active-panel')
    const inactive = wrapper.get('.list-panel:not(.active-panel)')

    await active.get('[data-testid="panel-warning-button"]').trigger('contextmenu')
    expect(rowNames(active)).toEqual(['broken'])
    expect(rowNames(inactive)).toEqual([])

    await active.get('.mod-row .icon-button.danger').trigger('click')
    await store.flushPlaysetUpdates()
    await flushPromises()

    expect(store.mods.map(item => item.id)).toEqual(['broken', 'healthy', 'available'])
    expect(store.activeIds).toEqual(['healthy'])
    expect(invokeMock).toHaveBeenCalledWith('save_load_order', ['healthy'], 'missing')
    expect(store.warningCount).toBe(0)
    expect(store.warningsOnly).toBe(false)
    expect(rowNames(active)).toEqual(['healthy'])
    expect(rowNames(inactive)).toEqual(['broken', 'available'])
  })

  it('disables only the selected warning MODs and restores the lists after a batch removal', async () => {
    store.mods.splice(1, 0, mod('also-broken', [{ code: 'missing_dependency', message: '缺少依赖：base.pack' }]))
    store.activeIds = ['broken', 'also-broken', 'healthy']
    store.playsets[0].mod_ids = [...store.activeIds]
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const active = wrapper.get('.active-panel')
    const inactive = wrapper.get('.list-panel:not(.active-panel)')

    await active.get('[data-testid="panel-warning-button"]').trigger('contextmenu')
    await active.get('[data-testid="mod-list"]').trigger('keydown', { key: 'a', ctrlKey: true })
    expect(store.selectedIds).toEqual(['broken', 'also-broken'])
    await active.get('.mod-row .icon-button.danger').trigger('click')
    await store.flushPlaysetUpdates()
    await flushPromises()

    expect(store.activeIds).toEqual(['healthy'])
    expect(store.mods).toHaveLength(4)
    expect(store.warningsOnly).toBe(false)
    expect(rowNames(active)).toEqual(['healthy'])
    expect(rowNames(inactive)).toEqual(['broken', 'also-broken', 'available'])
    expect(invokeMock).toHaveBeenCalledWith('save_load_order', ['healthy'], 'missing')
  })

  it('keeps a way out when a scan warning has no matching MOD rows', async () => {
    store.warnings = [{ code: 'scan_notice', message: '扫描提示' }]
    store.mods[0].warnings = []
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const active = wrapper.get('.active-panel')
    const inactive = wrapper.get('.list-panel:not(.active-panel)')

    await active.get('[data-testid="panel-warning-button"]').trigger('contextmenu')
    expect(rowNames(active)).toEqual([])
    expect(rowNames(inactive)).toEqual([])
    expect(store.warningsOnly).toBe(true)

    await inactive.get('[data-testid="clear-warning-filter"]').trigger('click')
    expect(store.warningsOnly).toBe(false)
    expect(rowNames(active)).toEqual(['broken', 'healthy'])
    expect(rowNames(inactive)).toEqual(['available'])
  })
})
