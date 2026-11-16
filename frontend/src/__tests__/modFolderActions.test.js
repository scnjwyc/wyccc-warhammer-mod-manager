import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import App from '../App.vue'
import { UNGROUPED_FOLDER } from '../modFolderLayout'
import { useAppStore } from '../store'

describe('folder filtering, batch enablement and MOD drops through the actual lists', () => {
  let wrapper
  let store
  let pinia
  let savedFolders
  const panel = active => wrapper.get(active ? '.active-panel' : '.list-panel:not(.active-panel)')
  const rowNames = active => panel(active).findAll('.row-title').map(row => row.text())
  const selectFolder = async (active, id) => {
    const filter = panel(active).get(`[data-testid="${active ? 'active' : 'inactive'}-folder-filter"]`)
    await filter.get('[role="combobox"]').trigger('click')
    await filter.get(`[role="option"][data-value="${id}"]`).trigger('click')
  }
  const mountApp = async () => {
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    for (const toggle of wrapper.findAll('[data-testid="toggle-folder-view"]')) await toggle.trigger('click')
    invokeMock.mockClear()
  }

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useAppStore()
    store.settings = { selected_game: 'warhammer3' }
    store.pathHealth = { game_ready: true }
    store.mods = ['a', 'b', 'c', 'd', 'e'].map(id => ({
      id, pack_name: `${id}.pack`, effective_name: id, source: 'data', pack_type: 'mod',
      hidden: id === 'c', warnings: id === 'd' ? [{ code: 'outdated', message: 'Check compatibility' }] : [],
    }))
    savedFolders = [
      { id: 'ui', name: '界面', mod_ids: ['a', 'c', 'd', 'missing'], collapsed_active: false, collapsed_inactive: true },
      { id: 'units', name: '单位', mod_ids: ['b'], collapsed_active: false, collapsed_inactive: false },
      { id: 'empty', name: '空文件夹', mod_ids: [], collapsed_active: false, collapsed_inactive: true },
    ]
    store.modFolders = structuredClone(savedFolders)
    store.activeIds = ['b', 'a']
    store.playsets = [{ id: 'default', name: 'Default', mod_ids: ['b', 'a'] }]
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    invokeMock.mockReset()
    invokeMock.mockImplementation(async (method, ...args) => {
      if (method === 'assign_mod_folder') {
        const ids = new Set(args[0])
        savedFolders = savedFolders.map(folder => ({
          ...folder,
          mod_ids: [...folder.mod_ids.filter(id => !ids.has(id)), ...(folder.id === args[1] ? ids : [])],
        }))
        return { game_id: 'warhammer3', playset_id: 'default', mod_folders: structuredClone(savedFolders) }
      }
      if (method === 'delete_mod_folder') {
        savedFolders = savedFolders.filter(folder => folder.id !== args[0])
        return { game_id: 'warhammer3', playset_id: 'default', mod_folders: structuredClone(savedFolders) }
      }
      if (method === 'save_load_order') return { order_token: 'saved', backup: null }
      if (method === 'get_diagnostics_history') return []
      return {}
    })
  })

  afterEach(async () => {
    wrapper?.unmount()
    wrapper = null
    await store.flushPlaysetUpdates()
    vi.restoreAllMocks()
  })

  it('filters each panel independently and combines folder selection with search, warnings and highlighting', async () => {
    await mountApp()
    await selectFolder(true, 'ui')
    expect(rowNames(true)).toEqual(['a'])
    expect(panel(true).findAll('.mod-folder-name').map(item => item.text())).toEqual(['界面'])
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['d', 'e'])
    await selectFolder(false, UNGROUPED_FOLDER)
    expect(rowNames(false)).toEqual(['e'])
    expect(panel(false).findAll('.mod-folder-row')).toHaveLength(0)
    await selectFolder(false, 'ui')
    store.inactiveSearchTokens = [{ type: 'text', value: 'd' }]
    store.warningsOnly = true
    await flushPromises()
    expect(rowNames(false)).toEqual(['d'])
    store.settings.inactive_search_highlight_mode = true
    store.inactiveSearchTokens = [{ type: 'text', value: 'e' }]
    await flushPromises()
    expect(rowNames(false)).toEqual(['d'])
    expect(store.inactiveSearchMatchIds).toEqual([])
    expect(panel(false).get('.mod-row').classes()).toContain('search-muted')
    await selectFolder(true, '')
    store.warningsOnly = false
    await flushPromises()
    expect(rowNames(true)).toEqual(['b', 'a'])
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('enables and disables every installed member even when search or hidden state excludes it, and supports undo', async () => {
    await mountApp()
    await selectFolder(false, 'ui')
    store.inactiveSearchTokens = [{ type: 'text', value: 'd' }]
    await flushPromises()
    expect(rowNames(false)).toEqual(['d'])
    expect(store.modFolderCounts.ui).toEqual({ active: 1, inactive: 2 })
    expect(panel(false).get('.mod-folder-toggle .count-badge').text()).toBe('2')
    await panel(false).get('[data-testid="enable-folder-ui"]').trigger('click')
    await store.flushPlaysetUpdates()
    await flushPromises()
    expect(store.activeIds).toEqual(['b', 'a', 'c', 'd'])
    expect(store.mods.find(mod => mod.id === 'c').hidden).toBe(true)
    expect(store.modFolders).toEqual(savedFolders)
    expect(invokeMock.mock.calls.filter(([method]) => method === 'update_playset')).toHaveLength(1)
    expect(invokeMock).toHaveBeenCalledWith('save_load_order', ['b', 'a', 'c', 'd'], 'missing')
    store.activeSearchTokens = [{ type: 'rule', key: 'name', value: 'a' }]
    await flushPromises()
    expect(rowNames(true)).toEqual(['a'])
    await panel(true).get('[data-testid="disable-folder-ui"]').trigger('click')
    await store.flushPlaysetUpdates()
    await flushPromises()
    expect(store.activeIds).toEqual(['b'])
    expect(store.modFolderCounts.ui).toEqual({ active: 0, inactive: 3 })
    await store.undoListChange()
    expect(store.activeIds).toEqual(['b', 'a', 'c', 'd'])
  })

  it('hides a folder after moving all members to the other panel and restores it when enabled again', async () => {
    await mountApp()
    await selectFolder(true, 'ui')
    await panel(true).get('[data-testid="disable-folder-ui"]').trigger('click')
    await store.flushPlaysetUpdates()
    await flushPromises()
    expect(rowNames(true)).toEqual([])
    expect(panel(true).findAll('.mod-folder-row')).toHaveLength(0)
    expect(panel(true).find('.empty-state').exists()).toBe(true)
    expect(panel(false).get('[data-testid="mod-folder-ui"] .count-badge').text()).toBe('3')
    await panel(false).get('[data-testid="enable-folder-ui"]').trigger('click')
    await store.flushPlaysetUpdates()
    await flushPromises()
    expect(store.activeIds).toEqual(['a', 'b', 'c', 'd'])
    expect(panel(true).get('[data-testid="mod-folder-ui"] .count-badge').text()).toBe('3')
    expect(panel(false).find('[data-testid="mod-folder-ui"]').exists()).toBe(false)
  })

  it('adds multiple MODs to a collapsed folder across panels and saves membership without changing enablement or order', async () => {
    store.selectedIds = ['a', 'b']
    store.activeSortMode = 'name'
    await mountApp()
    await panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b').trigger('dragstart')
    const target = panel(false).get('[data-testid="mod-folder-ui"]')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    expect(target.get('.mod-folder-toggle').attributes('aria-expanded')).toBe('false')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['b'], 'ui', 'warhammer3', 'default')
    expect(store.modFolders.find(folder => folder.id === 'ui').mod_ids).toContain('b')
    expect(store.modFolders.find(folder => folder.id === 'units').mod_ids).toEqual([])
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(store.dirty).toBe(false)
    expect(target.classes()).not.toContain('drop-inside')
    expect(invokeMock.mock.calls.some(([method]) => ['update_playset', 'save_load_order'].includes(method))).toBe(false)
    await selectFolder(true, 'ui')
    expect(rowNames(true)).toEqual(['a', 'b'])
    await store.dropModsIntoFolder({ folderId: 'ui', ids: ['a', 'b', 'missing', 'unknown'] })
    expect(invokeMock.mock.calls.filter(([method]) => method === 'assign_mod_folder')).toHaveLength(1)
  })

  it('keeps hidden empty folders in the context menu and restores them after assigning a MOD', async () => {
    await mountApp()
    expect(panel(true).find('[data-testid="mod-folder-empty"]').exists()).toBe(false)
    expect(panel(false).find('[data-testid="mod-folder-empty"]').exists()).toBe(true)
    const source = panel(false).get('.mod-row')
    await source.trigger('contextmenu', { clientX: 100, clientY: 100 })
    await wrapper.get('[data-testid="context-add-folder-empty"]').trigger('click')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['e'], 'empty', 'warhammer3', 'default')
    expect(store.activeIds).toEqual(['b', 'a'])
    await selectFolder(false, 'empty')
    expect(panel(false).get('.mod-folder-row .count-badge').text()).toBe('1')
    store.busy = 'Saving'
    await flushPromises()
    await panel(false).get('[data-testid="enable-folder-empty"]').trigger('click')
    await store.dropModsIntoFolder({ folderId: 'empty', ids: ['a'] })
    expect(invokeMock.mock.calls.filter(([method]) => method === 'assign_mod_folder')).toHaveLength(1)
    expect(store.activeIds).toEqual(['b', 'a'])
    store.busy = ''
  })

  it('assigns a MOD dropped on a member row of an expanded folder without changing enablement or load order', async () => {
    await mountApp()
    const source = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    const target = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'a')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(store.modFolders.find(folder => folder.id === 'ui').mod_ids).toContain('b')
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['b'], 'ui', 'warhammer3', 'default')
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(store.modFolders.find(folder => folder.id === 'units').mod_ids).toEqual([])
  })

  it('assigns a mixed selection onto a selected folder member even in name sorting', async () => {
    store.selectedIds = ['a', 'b']
    store.activeSortMode = 'name'
    await mountApp()
    const source = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    const target = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'a')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['b'], 'ui', 'warhammer3', 'default')
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(invokeMock.mock.calls.some(([method]) => ['update_playset', 'save_load_order'].includes(method))).toBe(false)
    expect(wrapper.findAll('.dragging, .drop-inside, .drop-before, .drop-after')).toHaveLength(0)
  })

  it('assigns through a folder member in the other panel without disabling the dragged MOD', async () => {
    savedFolders[0].collapsed_inactive = false
    store.modFolders = structuredClone(savedFolders)
    await mountApp()
    const source = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    const target = panel(false).findAll('.mod-row').find(row => row.get('.row-title').text() === 'd')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['b'], 'ui', 'warhammer3', 'default')
    expect(store.modFolders.find(folder => folder.id === 'ui').mod_ids).toContain('b')
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(invokeMock.mock.calls.some(([method]) => ['update_playset', 'save_load_order'].includes(method))).toBe(false)
    invokeMock.mockClear()
    const assignedSource = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    await assignedSource.trigger('dragstart')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).not.toHaveBeenCalled()
    expect(store.activeIds).toEqual(['b', 'a'])
  })

  it.each([
    { location: 'active list blank space', sourceActive: true, targetActive: true, sourceId: 'b', targetId: '' },
    { location: 'active ungrouped row', sourceActive: true, targetActive: true, sourceId: 'b', targetId: 'e' },
    { location: 'inactive list blank space', sourceActive: false, targetActive: false, sourceId: 'd', targetId: '' },
    { location: 'inactive ungrouped row', sourceActive: false, targetActive: false, sourceId: 'd', targetId: 'e' },
    { location: 'ungrouped row in the other panel', sourceActive: true, targetActive: false, sourceId: 'b', targetId: 'e' },
    { location: 'blank space in the other panel', sourceActive: true, targetActive: false, sourceId: 'b', targetId: '' },
    { location: 'active ungrouped row from the inactive panel', sourceActive: false, targetActive: true, sourceId: 'd', targetId: 'e' },
  ])('removes a grouped MOD dropped on $location without changing enablement or order', async ({ sourceActive, targetActive, sourceId, targetId }) => {
    savedFolders[0].collapsed_inactive = false
    store.modFolders = structuredClone(savedFolders)
    if (targetActive && targetId === 'e') store.activeIds = ['b', 'e', 'a']
    store.activeSortMode = 'name'
    const originalOrder = [...store.activeIds]
    await mountApp()
    const source = panel(sourceActive).get(`[data-mod-id="${sourceId}"]`)
    const target = panel(targetActive).get(targetId ? `[data-mod-id="${targetId}"]` : '.mod-list')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', [sourceId], '', 'warhammer3', 'default')
    expect(store.modFolders.every(folder => !folder.mod_ids.includes(sourceId))).toBe(true)
    expect(panel(sourceActive).get(`[data-mod-id="${sourceId}"]`).attributes('data-folder-id')).toBe('')
    expect(store.activeIds).toEqual(originalOrder)
    expect(store.dirty).toBe(false)
    expect(invokeMock.mock.calls.some(([method]) => ['update_playset', 'save_load_order'].includes(method))).toBe(false)
    expect(wrapper.findAll('.dragging, .drop-inside, .drop-before, .drop-after')).toHaveLength(0)
  })

  it('removes multiple grouped members from a mixed selection and skips already ungrouped MODs', async () => {
    store.activeIds = ['b', 'e', 'a']
    store.selectedIds = ['a', 'b', 'e']
    await mountApp()
    await panel(true).get('[data-mod-id="b"]').trigger('dragstart')
    const target = panel(true).get('.mod-list')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['b', 'a'], '', 'warhammer3', 'default')
    expect(store.modFolders.every(folder => !folder.mod_ids.includes('a') && !folder.mod_ids.includes('b'))).toBe(true)
    expect(store.modFolders.find(folder => folder.id === 'ui').mod_ids).toEqual(['c', 'd', 'missing'])
    expect(store.activeIds).toEqual(['b', 'e', 'a'])
    expect(invokeMock.mock.calls.filter(([method]) => method === 'assign_mod_folder')).toHaveLength(1)
    await store.dropModsIntoFolder({ ids: ['a', 'b', 'e', 'unknown'], folderId: '' })
    expect(invokeMock.mock.calls.filter(([method]) => method === 'assign_mod_folder')).toHaveLength(1)
  })

  it('hides a filtered folder after removing its last member and preserves its definition', async () => {
    await mountApp()
    await selectFolder(true, 'units')
    await panel(true).get('[data-mod-id="b"]').trigger('dragstart')
    await panel(true).get('.mod-list').trigger('dragover')
    await panel(true).get('.mod-list').trigger('drop')
    await flushPromises()
    expect(store.modFolders.find(folder => folder.id === 'units').mod_ids).toEqual([])
    expect(store.modFolderFilter('active')).toBe('units')
    expect(rowNames(true)).toEqual([])
    expect(panel(true).findAll('.mod-folder-row')).toHaveLength(0)
    expect(panel(true).find('.empty-state').exists()).toBe(true)
    expect(store.activeIds).toEqual(['b', 'a'])
    await selectFolder(true, UNGROUPED_FOLDER)
    expect(rowNames(true)).toEqual(['b'])
  })

  it('keeps membership and allows an immediate retry when removing a grouped MOD fails', async () => {
    await mountApp()
    invokeMock.mockRejectedValueOnce(new Error('Save failed'))
    const source = panel(true).get('[data-mod-id="b"]')
    const target = panel(false).get('[data-mod-id="e"]')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(store.modFolders).toEqual(savedFolders)
    expect(store.toast.type).toBe('error')
    expect(store.busy).toBe('')
    expect(wrapper.findAll('.dragging, .drop-inside, .drop-before, .drop-after')).toHaveLength(0)
    await source.trigger('dragstart')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(store.modFolders.find(folder => folder.id === 'units').mod_ids).toEqual([])
    expect(store.activeIds).toEqual(['b', 'a'])
  })

  it('still enables an ungrouped MOD dropped into the other list', async () => {
    await mountApp()
    await panel(false).get('[data-mod-id="e"]').trigger('dragstart')
    await panel(true).get('.mod-list').trigger('dragover')
    await panel(true).get('.mod-list').trigger('drop')
    await store.flushPlaysetUpdates()
    await flushPromises()
    expect(store.activeIds).toEqual(['b', 'a', 'e'])
    expect(store.modFolders).toEqual(savedFolders)
    expect(invokeMock.mock.calls.some(([method]) => method === 'assign_mod_folder')).toBe(false)
    expect(invokeMock).toHaveBeenCalledWith('save_load_order', ['b', 'a', 'e'], 'missing')
  })

  it('keeps membership when an outside drop is cancelled or the store is busy', async () => {
    await mountApp()
    const source = panel(true).get('[data-mod-id="b"]')
    const target = panel(true).get('.mod-list')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    await source.trigger('dragend')
    expect(store.modFolders).toEqual(savedFolders)
    expect(wrapper.findAll('.dragging, .drop-inside, .drop-before, .drop-after')).toHaveLength(0)
    await source.trigger('dragstart')
    store.busy = 'Saving'
    await flushPromises()
    await target.trigger('drop')
    await store.dropModsIntoFolder({ ids: ['b'], folderId: '' })
    expect(invokeMock).not.toHaveBeenCalled()
    expect(store.modFolders).toEqual(savedFolders)
    expect(store.activeIds).toEqual(['b', 'a'])
    store.busy = ''
  })

  it('preserves saved membership and clears feedback when assigning the dragged MOD fails', async () => {
    await mountApp()
    invokeMock.mockRejectedValueOnce(new Error('Save failed'))
    await panel(false).get('.mod-row').trigger('dragstart')
    const target = panel(false).get('[data-testid="mod-folder-ui"]')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(store.modFolders).toEqual(savedFolders)
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(store.toast.type).toBe('error')
    expect(store.busy).toBe('')
    expect(target.classes()).not.toContain('drop-inside')
  })

  it('recovers both lists after a failed folder drop and allows an immediate retry without a source dragend', async () => {
    await mountApp()
    invokeMock.mockRejectedValueOnce(new Error('Save failed'))
    const source = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    const target = panel(false).get('[data-testid="mod-folder-ui"]')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    await target.trigger('drop')
    await flushPromises()
    expect(store.modFolders).toEqual(savedFolders)
    expect(wrapper.findAll('.dragging, .drop-inside, .drop-before, .drop-after')).toHaveLength(0)
    expect(source.attributes('draggable')).toBe('true')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    await target.trigger('drop')
    await flushPromises()
    expect(store.modFolders.find(folder => folder.id === 'ui').mod_ids).toContain('b')
    expect(store.activeIds).toEqual(['b', 'a'])
  })

  it('does not confuse a new MOD drag with a completed folder drag whose native dragend was missed', async () => {
    await mountApp()
    const sourceFolder = panel(true).get('[data-testid="mod-folder-units"]')
    const otherPanelFolder = panel(false).get('[data-testid="mod-folder-ui"]')
    await sourceFolder.trigger('dragstart')
    await otherPanelFolder.trigger('dragover')
    await otherPanelFolder.trigger('drop')
    await flushPromises()
    invokeMock.mockClear()
    const sourceMod = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    const target = panel(true).get('[data-testid="mod-folder-ui"]')
    await sourceMod.trigger('dragstart')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['b'], 'ui', 'warhammer3', 'default')
    expect(store.modFolders.find(folder => folder.id === 'ui').mod_ids).toContain('b')
    expect(store.activeIds).toEqual(['b', 'a'])
  })

  it('accepts a MOD from the other list after a cancelled folder drag without native dragend', async () => {
    await mountApp()
    const target = panel(false).get('[data-testid="mod-folder-ui"]')
    await target.trigger('dragstart')
    const source = panel(true).findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    await target.trigger('drop')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('assign_mod_folder', ['b'], 'ui', 'warhammer3', 'default')
    expect(store.modFolders.find(folder => folder.id === 'ui').mod_ids).toContain('b')
    expect(wrapper.findAll('.dragging, .drop-inside, .drop-before, .drop-after')).toHaveLength(0)
    expect(store.activeIds).toEqual(['b', 'a'])
  })

  it('restores all MODs when the selected folder is deleted and clears folder filters on game changes', async () => {
    await mountApp()
    await selectFolder(true, 'ui')
    await store.deleteModFolder('ui')
    await flushPromises()
    expect(store.modFolderFilter('active')).toBe('')
    expect(rowNames(true)).toEqual(['b', 'a'])
    expect(panel(true).get('[role="combobox"]').text()).toBe('全部文件夹')
    store.setModFolderFilter('inactive', UNGROUPED_FOLDER)
    store.clearGameContextData()
    expect(store.modFolderFilters).toEqual({ active: '', inactive: '' })
  })
})
