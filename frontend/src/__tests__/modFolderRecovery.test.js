import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import App from '../App.vue'
import { useAppStore } from '../store'

describe('folder movement and playset recovery through the actual lists', () => {
  let wrapper
  let store
  let pinia
  let layouts
  const folder = { id: 'ui', name: 'UI', mod_ids: ['a'], collapsed_active: false, collapsed_inactive: true }
  const second = { ...folder, id: 'units', name: '单位', mod_ids: ['c'] }
  const groupNames = panel => [...panel.get('.mod-list').element.children]
    .filter(element => element.matches('.mod-folder-row, .mod-row'))
    .map(element => element.querySelector('.mod-folder-name, .row-title').textContent)

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useAppStore()
    store.settings = { selected_game: 'warhammer3' }
    store.pathHealth = { game_ready: true }
    store.mods = ['a', 'b', 'c'].map(id => ({
      id, pack_name: `${id}.pack`, effective_name: id, source: 'data', pack_type: 'mod', warnings: [],
    }))
    store.modFolders = [folder, second]
    store.activeIds = ['a', 'b', 'c']
    store.playsets = [{ id: 'default', name: 'Default', mod_ids: ['a', 'b', 'c'] }, { id: 'other', name: 'Other', mod_ids: ['b'] }]
    layouts = { active: [], inactive: [] }
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    invokeMock.mockReset()
    invokeMock.mockImplementation(async (method, ...args) => {
      if (method === 'reorder_mod_folder_groups') {
        layouts = { ...layouts, [args[0]]: [...args[1]] }
        return { game_id: 'warhammer3', playset_id: store.currentPlaysetId, mod_folders: [folder, second], mod_folder_layouts: layouts }
      }
      if (method === 'switch_playset') return {
        current_playset: store.playsets.find(item => item.id === args[0]),
        ordered_mod_ids: args[0] === 'other' ? ['b'] : ['a', 'b', 'c'],
        missing_mod_ids: [], mod_folders: [folder, second], mod_folder_layouts: layouts,
      }
      if (method === 'save_load_order') return { ordered_mod_ids: args[0], order_token: 'saved' }
      if (method === 'get_diagnostics_history') return []
      return {}
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    vi.restoreAllMocks()
  })

  it('drags a folder below a loose MOD, saves the position and retains it when switching playsets', async () => {
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const active = wrapper.get('.active-panel')
    expect(groupNames(active)).toEqual(['UI', 'a', 'b', '单位', 'c'])
    await active.get('[data-testid="mod-folder-ui"]').trigger('dragstart')
    const loose = active.findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    await loose.trigger('dragover', { clientY: 1 })
    await loose.trigger('drop', { clientY: 1 })
    await flushPromises()
    expect(groupNames(active)).toEqual(['b', 'UI', 'a', '单位', 'c'])
    expect(invokeMock).toHaveBeenCalledWith('reorder_mod_folder_groups', 'active',
      ['mod:b', 'folder:ui', 'folder:units'], 'warhammer3', 'default')
    expect(store.activeIds).toEqual(['a', 'b', 'c'])
    expect(invokeMock.mock.calls.some(([method]) => ['update_playset', 'save_load_order'].includes(method))).toBe(false)
    expect(active.findAll('.thumbnail-order').map(item => item.text())).toEqual(['2', '1', '3'])

    await store.switchPlayset('other')
    await store.flushPlaysetUpdates()
    await flushPromises()
    expect(groupNames(active)).toEqual(['b'])
    expect(store.modFolders.map(item => item.id)).toEqual(['ui', 'units'])
    expect(store.activeIds).toEqual(['b'])
    await store.switchPlayset('default')
    await store.flushPlaysetUpdates()
    await flushPromises()
    expect(groupNames(active)).toEqual(['b', 'UI', 'a', '单位', 'c'])
    expect(store.activeIds).toEqual(['a', 'b', 'c'])
  })

  it('moves collapsed folders in the inactive panel independently of active positions', async () => {
    store.activeIds = ['b']
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const inactive = wrapper.get('.list-panel:not(.active-panel)')
    await inactive.get('[data-testid="mod-folder-ui"]').trigger('dragstart')
    await inactive.get('[data-testid="mod-folder-units"]').trigger('dragover', { clientY: 1 })
    await inactive.get('[data-testid="mod-folder-units"]').trigger('drop', { clientY: 1 })
    await flushPromises()
    expect(groupNames(inactive)).toEqual(['单位', 'UI'])
    expect(store.modFolderLayouts.active).toEqual([])
    expect(store.modFolderLayouts.inactive).toEqual(['folder:units', 'folder:ui'])
    expect(store.activeIds).toEqual(['b'])
  })

  it('keeps the original display and saved state when dragging cannot be saved', async () => {
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const active = wrapper.get('.active-panel')
    invokeMock.mockRejectedValueOnce(new Error('save failed'))
    await active.get('[data-testid="mod-folder-ui"]').trigger('dragstart')
    await active.get('[data-testid="mod-folder-units"]').trigger('drop', { clientY: 1 })
    await flushPromises()
    expect(groupNames(active)).toEqual(['UI', 'a', 'b', '单位', 'c'])
    expect(store.modFolderLayouts.active).toEqual([])
    expect(store.toast.type).toBe('error')
    expect(store.busy).toBe('')
  })

  it('defaults to folders, then ignores grouping and folder filters in the flat view without changing saved data', async () => {
    store.activeIds = ['c', 'b', 'a']
    store.modFolderLayouts.active = ['folder:ui', 'mod:b', 'folder:units']
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const toggle = wrapper.get('[data-testid="hide-mod-folders"]')
    const active = wrapper.get('.active-panel')
    expect(toggle.element.checked).toBe(false)
    expect(active.findAll('.mod-folder-row')).toHaveLength(2)
    store.setModFolderFilter('active', 'ui')
    await flushPromises()
    expect(active.findAll('.mod-row').map(row => row.get('.row-title').text())).toEqual(['a'])
    const before = JSON.stringify({ folders: store.modFolders, layouts: store.modFolderLayouts, order: store.activeIds })
    invokeMock.mockClear()
    await toggle.setValue(true)
    expect(active.find('.mod-folder-row').exists()).toBe(false)
    expect(active.find('[data-testid="active-folder-filter"]').exists()).toBe(false)
    expect(active.findAll('.mod-row').map(row => row.get('.row-title').text())).toEqual(['c', 'b', 'a'])
    expect(JSON.stringify({ folders: store.modFolders, layouts: store.modFolderLayouts, order: store.activeIds })).toBe(before)
    expect(invokeMock).not.toHaveBeenCalled()
    await toggle.setValue(false)
    expect(active.find('[data-testid="mod-folder-ui"]').exists()).toBe(true)
    expect(store.modFolderFilter('active')).toBe('ui')
  })

  it('makes collapsed inactive folder members available to search and dragging in flat view', async () => {
    store.activeIds = ['b']
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    const inactive = wrapper.get('.list-panel:not(.active-panel)')
    expect(inactive.findAll('.mod-row')).toHaveLength(0)
    await wrapper.get('[data-testid="hide-mod-folders"]').setValue(true)
    expect(inactive.findAll('.mod-row').map(row => row.get('.row-title').text())).toEqual(['a', 'c'])
    store.selectedIds = ['a']
    const rows = inactive.findAll('.mod-row')
    await rows[0].trigger('dragstart')
    await rows[1].trigger('drop', { clientY: 1 })
    await flushPromises()
    expect(invokeMock.mock.calls.some(([method]) => method === 'assign_mod_folder')).toBe(false)
    expect(store.modFolders[0].mod_ids).toEqual(['a'])
  })
})
