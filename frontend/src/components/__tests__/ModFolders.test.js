import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ModList from '../ModList.vue'
import ModContextMenu from '../ModContextMenu.vue'

const mods = ['a', 'b', 'c'].map(id => ({ id, effective_name: id, pack_name: `${id}.pack`, source: 'data' }))
const folder = { id: 'folder', name: '界面', mod_ids: ['a', 'c'], collapsed_active: false, collapsed_inactive: false }
const list = (overrides = {}) => mount(ModList, { props: { title: 'MOD', mods, folders: [folder], foldersVisible: true, ...overrides } })

describe('MOD folder list', () => {
  it.each([false, true])('puts name-sorted folders before loose MODs in the active=%s panel', async active => {
    const folders = [
      { id: 'last', name: 'Group 10', mod_ids: ['a'] },
      { id: 'empty', name: 'Alpha', mod_ids: [] },
      { id: 'first', name: 'Group 2', mod_ids: ['c'] },
    ]
    const wrapper = list({ active, mods: [mods[1], mods[0], mods[2]], folders,
      folderLayout: ['mod:b', 'folder:last', 'folder:first'] })
    expect(wrapper.findAll('.mod-folder-name').map(item => item.text()))
      .toEqual(active ? ['Group 2', 'Group 10'] : ['Alpha', 'Group 2', 'Group 10'])
    const children = [...wrapper.get('.mod-list').element.children].filter(item => item.matches('.mod-row, .mod-folder-row'))
    expect(children.at(-1).dataset.modId).toBe('b')
    await wrapper.setProps({ folders: folders.map(item => item.id === 'last' ? { ...item, name: 'Aardvark' } : item) })
    expect(wrapper.findAll('.mod-folder-name')[0].text()).toBe('Aardvark')
    await wrapper.setProps({ foldersVisible: false })
    expect(wrapper.findAll('.row-title').map(item => item.text())).toEqual(['b', 'a', 'c'])
    wrapper.unmount()
  })
  it('keeps flat-view dragging as an ordering operation without removing folder membership', async () => {
    const wrapper = list({ foldersVisible: false, active: true, orderIds: ['a', 'b', 'c'] })
    expect(wrapper.findAll('.row-title').map(item => item.text())).toEqual(['a', 'b', 'c'])
    await wrapper.get('[data-mod-id="a"]').trigger('dragstart')
    await wrapper.get('[data-mod-id="b"]').trigger('drop')
    expect(wrapper.emitted('drop-in-folder')).toBeUndefined()
    expect(wrapper.emitted('drop-mods')[0][0]).toMatchObject({ ids: ['a'], targetId: 'b' })
    expect(wrapper.props('folders')[0].mod_ids).toEqual(['a', 'c'])
    wrapper.unmount()
  })
  it('accepts a MOD transfer onto the header and ignores unrelated or invalid drag data', async () => {
    const wrapper = list()
    const target = wrapper.get('[data-testid="mod-folder-folder"]')
    const transfer = encoded => ({ getData: type => type === 'application/x-wyccc-mods' ? encoded : '' })
    await target.trigger('drop', { dataTransfer: transfer(JSON.stringify({ source: 'active', ids: ['b', 'c'] })) })
    expect(wrapper.emitted('drop-in-folder')).toEqual([[{ folderId: 'folder', ids: ['b', 'c'] }]])
    await target.trigger('drop', { dataTransfer: transfer('invalid') })
    await target.trigger('drop', { dataTransfer: transfer(JSON.stringify({ source: 'external', ids: ['a'] })) })
    expect(wrapper.emitted('drop-in-folder')).toHaveLength(1)
    expect(wrapper.emitted('drop-mods')).toBeUndefined()
    expect(wrapper.emitted('move-folder')).toBeUndefined()
    wrapper.unmount()
  })

  it('clears the folder highlight when a MOD drag leaves or ends without dropping', async () => {
    const wrapper = list()
    const source = wrapper.findAll('.mod-row').find(row => row.get('.row-title').text() === 'b')
    const target = wrapper.get('[data-testid="mod-folder-folder"]')
    await source.trigger('dragstart')
    await target.trigger('dragover')
    expect(target.classes()).toContain('drop-inside')
    await target.trigger('dragleave')
    expect(target.classes()).not.toContain('drop-inside')
    await target.trigger('dragover')
    await source.trigger('dragend')
    expect(target.classes()).not.toContain('drop-inside')
    expect(wrapper.emitted('drop-in-folder')).toBeUndefined()
    wrapper.unmount()
  })

  it('adds a transferred MOD through a folder member row and clears its inside marker', async () => {
    const wrapper = list()
    const target = wrapper.findAll('.mod-row').find(row => row.get('.row-title').text() === 'a')
    const dataTransfer = {
      types: ['application/x-wyccc-mods'],
      getData: type => type === 'application/x-wyccc-mods' ? JSON.stringify({ source: 'active', ids: ['b'] }) : '',
    }
    await target.trigger('dragover', { dataTransfer })
    expect(target.classes()).toContain('drop-inside')
    await target.trigger('drop', { dataTransfer })
    expect(wrapper.emitted('drop-in-folder')).toEqual([[{ ids: ['b'], folderId: 'folder' }]])
    expect(wrapper.emitted('drop-mods')).toBeUndefined()
    expect(wrapper.findAll('.drop-inside')).toHaveLength(0)
    wrapper.unmount()
  })

  it('keeps normal insertion and sorting for members dragged within the same folder', async () => {
    const wrapper = list({ active: true, orderIds: ['a', 'c', 'b'] })
    const source = wrapper.findAll('.mod-row').find(row => row.get('.row-title').text() === 'a')
    const target = wrapper.findAll('.mod-row').find(row => row.get('.row-title').text() === 'c')
    await source.trigger('dragstart')
    await target.trigger('dragover', { clientY: -1 })
    expect(target.classes()).toContain('drop-before')
    expect(target.classes()).not.toContain('drop-inside')
    await target.trigger('drop')
    expect(wrapper.emitted('drop-mods')[0][0]).toMatchObject({ ids: ['a'], source: 'active', target: 'active', targetId: 'c', placement: 'before' })
    expect(wrapper.emitted('drop-in-folder')).toBeUndefined()
    wrapper.unmount()
  })

  it('drags a folder below another folder without dragging MODs or changing load order', async () => {
    const other = { ...folder, id: 'other', name: '其他', mod_ids: ['b'] }
    const wrapper = list({ active: true, orderIds: ['a', 'b', 'c'], folders: [folder, other] })
    const source = wrapper.get('[data-testid="mod-folder-folder"]')
    const target = wrapper.get('[data-testid="mod-folder-other"]')
    expect(source.attributes('draggable')).toBe('false')
    await source.trigger('dragstart')
    await target.trigger('dragover', { clientY: 1 })
    await target.trigger('drop', { clientY: 1 })
    expect(wrapper.emitted('move-folder')[0][0]).toEqual({
      folderId: 'folder', targetFolderId: 'other', targetModId: '', placement: 'after', listName: 'active',
    })
    expect(wrapper.emitted('drop-mods')).toBeUndefined()
    expect(wrapper.emitted('drag-start')).toBeUndefined()
    expect(wrapper.props('orderIds')).toEqual(['a', 'b', 'c'])
  })

  it('groups members while retaining their real load-order numbers', () => {
    const wrapper = list({ active: true, orderIds: ['a', 'b', 'c'] })
    expect(wrapper.findAll('.mod-folder-row')).toHaveLength(1)
    expect(wrapper.findAll('.row-title').map(item => item.text())).toEqual(['a', 'c', 'b'])
    expect(wrapper.findAll('.thumbnail-order').map(item => item.text())).toEqual(['1', '3', '2'])
    expect(wrapper.findAll('.mod-row.in-folder')).toHaveLength(2)
    expect(wrapper.get('.mod-folder-toggle .count-badge').text()).toBe('2')
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

  it('shows empty folders in the inactive panel but hides them during search', async () => {
    const wrapper = list({ folders: [folder, { ...folder, id: 'empty', name: '空文件夹', mod_ids: [] }] })
    expect(wrapper.findAll('.mod-folder-row')).toHaveLength(2)
    expect(wrapper.find('[data-testid="mod-folder-empty"]').exists()).toBe(true)
    await wrapper.setProps({ mods: [mods[1]], searchTokens: [{ value: 'b' }] })
    expect(wrapper.findAll('.mod-folder-row')).toHaveLength(0)
  })

  it('hides folders with no visible members and restores them when a member returns', async () => {
    const wrapper = list({ mods: [], active: true })
    expect(wrapper.find('[data-testid="mod-folder-folder"]').exists()).toBe(false)
    expect(wrapper.findAll('.mod-row')).toHaveLength(0)
    expect(wrapper.find('.empty-state').exists()).toBe(true)
    await wrapper.setProps({ mods: [mods[0]] })
    expect(wrapper.get('[data-testid="mod-folder-folder"] .count-badge').text()).toBe('1')
  })

  it('shows the panel member count beside the name while collapsed or searching', async () => {
    const wrapper = list({
      mods: [mods[0]], folders: [{ ...folder, collapsed_inactive: true }],
      folderModCounts: { folder: { active: 1, inactive: 2 } },
    })
    expect(wrapper.findAll('.mod-row')).toHaveLength(0)
    expect(wrapper.get('.mod-folder-toggle .count-badge').text()).toBe('2')
    await wrapper.setProps({ searchTokens: [{ value: 'a' }] })
    expect(wrapper.findAll('.mod-row')).toHaveLength(1)
    expect(wrapper.get('.mod-folder-toggle .count-badge').text()).toBe('2')
    await wrapper.setProps({ active: true })
    expect(wrapper.get('.mod-folder-toggle .count-badge').text()).toBe('1')
  })

  it('moves a collapsed folder onto a plain MOD and can render the saved position', async () => {
    const wrapper = list({ folders: [{ ...folder, collapsed_inactive: true }] })
    await wrapper.get('[data-testid="mod-folder-folder"]').trigger('dragstart')
    await wrapper.get('.mod-row').trigger('dragover', { clientY: 1 })
    await wrapper.get('.mod-row').trigger('drop', { clientY: 1 })
    expect(wrapper.emitted('move-folder')[0][0]).toEqual({
      folderId: 'folder', targetFolderId: '', targetModId: 'b', placement: 'after', listName: 'inactive',
    })
    await wrapper.setProps({ folderLayout: ['mod:b', 'folder:folder'] })
    expect(wrapper.get('.mod-list').element.firstElementChild.classList.contains('mod-folder-row')).toBe(true)
    expect(wrapper.get('.mod-folder-toggle').attributes('aria-expanded')).toBe('false')
  })

  it('prevents folder movement while busy and never interprets a folder drag as a MOD drop', async () => {
    const wrapper = list({ busy: true, dragSource: { kind: 'folder', folderId: 'folder', source: 'active' } })
    expect(wrapper.get('.mod-folder-row').attributes('draggable')).toBe('false')
    await wrapper.get('.mod-row').trigger('drop')
    expect(wrapper.emitted('move-folder')).toBeUndefined()
    expect(wrapper.emitted('drop-mods')).toBeUndefined()
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
