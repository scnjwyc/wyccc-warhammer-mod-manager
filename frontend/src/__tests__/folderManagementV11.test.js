import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import App from '../App.vue'
import { useAppStore } from '../store'

describe('V1.1 folder management', () => {
  let wrapper, store, pinia
  const folder = { id: 'ui', name: 'UI', mod_ids: ['a', 'c'], collapsed_active: false, collapsed_inactive: false }
  const panel = active => wrapper.get(active ? '.active-panel' : '.list-panel:not(.active-panel)')
  const names = active => panel(active).findAll('.row-title').map(item => item.text())
  const start = async () => {
    wrapper = mount(App, { attachTo: document.body, global: { plugins: [pinia] } })
    await flushPromises()
  }
  const openMenu = async () => {
    await panel(true).get('[data-testid="toggle-folder-view"]').trigger('click')
    await panel(true).get('[data-testid="mod-folder-ui"]').trigger('contextmenu', { clientX: 400, clientY: 300 })
  }
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useAppStore()
    store.settings = { selected_game: 'warhammer3' }
    store.mods = ['a', 'b', 'c'].map(id => ({ id, effective_name: id, pack_name: `${id}.pack`, source: 'data', warnings: [] }))
    store.activeIds = ['a', 'b', 'c']
    store.playsets = [{ id: 'default', name: 'Default', mod_ids: ['a', 'b', 'c'] }]
    store.modFolders = [structuredClone(folder)]
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    invokeMock.mockReset()
    invokeMock.mockImplementation(async method => method === 'get_diagnostics_history' ? [] : {})
  })
  afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.restoreAllMocks() })

  it('defaults both lists to flat and restores real order after independent view toggles', async () => {
    await start()
    expect(wrapper.findAll('.mod-folder-row')).toHaveLength(0)
    expect(names(true)).toEqual(['a', 'b', 'c'])
    await panel(true).get('[data-testid="toggle-folder-view"]').trigger('click')
    expect(names(true)).toEqual(['a', 'c', 'b'])
    expect(panel(false).get('[data-testid="toggle-folder-view"]').attributes('aria-pressed')).toBe('false')
    store.setModFolderFilter('active', 'ui')
    await flushPromises()
    expect(names(true)).toEqual(['a', 'c'])
    await panel(true).get('[data-testid="toggle-folder-view"]').trigger('click')
    expect(names(true)).toEqual(['a', 'b', 'c'])
    expect(store.activeIds).toEqual(['a', 'b', 'c'])
    expect(invokeMock.mock.calls.some(([method]) => ['save_load_order', 'update_playset'].includes(method))).toBe(false)
  })

  it('creates an empty named folder from the inactive panel and shows it immediately', async () => {
    invokeMock.mockImplementation(async method => method === 'create_mod_folder' ? {
      game_id: 'warhammer3', playset_id: 'default', mod_folders: [folder, { id: 'empty', name: '新文件夹', mod_ids: [] }],
    } : method === 'get_diagnostics_history' ? [] : {})
    await start()
    await panel(false).get('[data-testid="create-empty-folder"]').trigger('click')
    const input = document.querySelector('[data-testid="folder-name-input"]')
    input.value = '新文件夹'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector('.folder-name-modal').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('create_mod_folder', '新文件夹', [], 'warhammer3', 'default')
    expect(panel(false).get('[data-testid="mod-folder-empty"]').text()).toContain('新文件夹')
    expect(panel(true).findAll('.mod-folder-row')).toHaveLength(0)
  })

  it('releases every member through the folder menu without changing enablement', async () => {
    vi.spyOn(store, 'releaseModFolder').mockResolvedValue({})
    await start()
    await openMenu()
    await document.querySelector('[data-testid="folder-action-release"]').click()
    await flushPromises()
    expect(store.releaseModFolder).toHaveBeenCalledWith('ui')
    expect(store.activeIds).toEqual(['a', 'b', 'c'])
  })

  it('lists affected names and playsets, does nothing on cancel and only executes after confirmation', async () => {
    vi.spyOn(store, 'previewFolderUnsubscribe').mockResolvedValue({
      token: 'confirmed-snapshot', folder, targets: [{ id: 'a', workshop_id: '123' }],
      affected_mods: [{ id: 'a', name: 'Workshop A' }, { id: 'other', name: 'Other pack from same item' }],
      affected_playsets: ['Campaign B'], skipped: ['c'],
    })
    vi.spyOn(store, 'unsubscribeModFolder').mockResolvedValue({ failed_count: 0, completed_count: 1 })
    await start()
    await openMenu()
    document.querySelector('[data-testid="folder-action-unsubscribe"]').click()
    await flushPromises()
    const message = document.querySelector('.confirmation-message').textContent
    expect(message).toContain('Workshop A')
    expect(message).toContain('Other pack from same item')
    expect(message).toContain('Campaign B')
    expect(store.unsubscribeModFolder).not.toHaveBeenCalled()
    document.querySelector('.confirmation-modal-footer .secondary-button').click()
    await flushPromises()
    expect(store.unsubscribeModFolder).not.toHaveBeenCalled()
    await panel(true).get('[data-testid="mod-folder-ui"]').trigger('contextmenu')
    document.querySelector('[data-testid="folder-action-unsubscribe"]').click()
    await flushPromises()
    document.querySelector('[data-testid="confirmation-confirm"]').click()
    await flushPromises()
    expect(store.unsubscribeModFolder).toHaveBeenCalledExactlyOnceWith('confirmed-snapshot')
  })
})
