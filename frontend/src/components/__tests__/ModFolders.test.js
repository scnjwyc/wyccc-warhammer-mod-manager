import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ModList from '../ModList.vue'
import ModContextMenu from '../ModContextMenu.vue'

const mods = ['a', 'b', 'c'].map(id => ({ id, effective_name: id, pack_name: `${id}.pack`, source: 'data' }))
const folder = { id: 'folder', name: '界面', mod_ids: ['a', 'c'], collapsed_active: false, collapsed_inactive: false }
const list = (overrides = {}) => mount(ModList, { props: { title: 'MOD', mods, folders: [folder], ...overrides } })

describe('MOD folder list', () => {
  it('groups members while retaining their real load-order numbers', () => {
    const wrapper = list({ active: true, orderIds: ['a', 'b', 'c'] })
    expect(wrapper.findAll('.mod-folder-row')).toHaveLength(1)
    expect(wrapper.findAll('.row-title').map(item => item.text())).toEqual(['a', 'c', 'b'])
    expect(wrapper.findAll('.thumbnail-order').map(item => item.text())).toEqual(['1', '3', '2'])
    expect(wrapper.findAll('.mod-row.in-folder')).toHaveLength(2)
    expect(wrapper.get('.mod-folder-row .count-badge').text()).toBe('2')
  })

  it('collapses members and uses only visible rows for selection and dragging', async () => {
    const wrapper = list({ folders: [{ ...folder, collapsed_inactive: true }], selectedIds: ['a', 'b', 'c'] })
    expect(wrapper.findAll('.row-title').map(item => item.text())).toEqual(['b'])
    expect(wrapper.get('.mod-folder-toggle').attributes('aria-expanded')).toBe('false')
    await wrapper.get('.mod-folder-toggle').trigger('click')
    expect(wrapper.emitted('toggle-folder')[0]).toEqual(['folder', 'inactive'])
    await wrapper.get('.mod-list').trigger('keydown', { key: 'a', ctrlKey: true })
    expect(wrapper.emitted('select-all')[0][0]).toEqual(['b'])
    await wrapper.get('.mod-row').trigger('click', { shiftKey: true })
    expect(wrapper.emitted('select')[0][0].orderedIds).toEqual(['b'])
    await wrapper.get('.mod-row').trigger('dragstart')
    expect(wrapper.emitted('drag-start')[0][0].ids).toEqual(['b'])
  })

  it('opens folders during search and restores saved collapse after clearing it', async () => {
    const wrapper = list({ folders: [{ ...folder, collapsed_inactive: true }] })
    await wrapper.setProps({ mods: [mods[2]], searchTokens: [{ value: 'c' }] })
    expect(wrapper.get('.row-title').text()).toBe('c')
    expect(wrapper.get('.mod-folder-toggle').attributes('aria-expanded')).toBe('true')
    await wrapper.setProps({ mods, searchTokens: [] })
    expect(wrapper.findAll('.row-title').map(item => item.text())).toEqual(['b'])
  })

  it('keeps empty folders available and hides folders with no results in a filtered list', async () => {
    const wrapper = list({ folders: [folder, { ...folder, id: 'empty', name: '空文件夹', mod_ids: [] }] })
    expect(wrapper.findAll('.mod-folder-row')).toHaveLength(2)
    await wrapper.setProps({ mods: [mods[1]], searchTokens: [{ value: 'b' }] })
    expect(wrapper.findAll('.mod-folder-row')).toHaveLength(0)
  })

  it('uses independent collapse states for the enabled and disabled panels', async () => {
    const wrapper = list({ folders: [{ ...folder, collapsed_active: true }], active: false })
    expect(wrapper.findAll('.mod-row')).toHaveLength(3)
    await wrapper.setProps({ active: true })
    expect(wrapper.findAll('.mod-row')).toHaveLength(1)
  })

  it('emits folder management actions without selecting or toggling MODs', async () => {
    const wrapper = list()
    await wrapper.get('.mod-folder-row [aria-label="重命名文件夹"]').trigger('click')
    await wrapper.get('.mod-folder-row [aria-label="删除文件夹"]').trigger('click')
    expect(wrapper.emitted('rename-folder')[0][0]).toEqual(folder)
    expect(wrapper.emitted('delete-folder')[0][0]).toEqual(folder)
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(wrapper.emitted('toggle-active')).toBeUndefined()
  })
})

describe('MOD folder context menu', () => {
  it('offers creation, existing destinations and removal for a batch', async () => {
    const wrapper = mount(ModContextMenu, { props: {
      open: true, mod: mods[0], folders: [folder], selectionCount: 2, selectedModIds: ['a', 'b'],
    } })
    expect(wrapper.get('[data-testid="context-folder-menu"]').text()).toContain('添加到文件夹（2项）')
    await wrapper.get('[data-testid="context-create-folder"]').trigger('click')
    await wrapper.get('[data-testid="context-add-folder-folder"]').trigger('click')
    await wrapper.get('[data-testid="context-remove-folder"]').trigger('click')
    expect(wrapper.emitted('action').map(([item]) => [item.action, item.value])).toEqual([
      ['create-folder', null], ['add-to-folder', 'folder'], ['remove-from-folder', null],
    ])
  })

  it('offers folder creation before any folders exist', () => {
    const wrapper = mount(ModContextMenu, { props: { open: true, mod: mods[0] } })
    expect(wrapper.find('[data-testid="context-create-folder"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="context-remove-folder"]').exists()).toBe(false)
  })
})
