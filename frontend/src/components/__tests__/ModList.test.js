import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import ModList from '../ModList.vue'

const duplicateMod = {
  id: 'local:data:same',
  effective_name: 'Same Mod',
  display_name: 'Same Mod',
  pack_name: 'same.pack',
  source: 'data',
  sources: ['data', 'workshop'],
  cross_source_duplicate: true,
  pack_type: 'mod',
  workshop_id: '123',
  author: 'Example Author',
  mod_type: 'overhaul',
  hidden: false,
}

describe('ModList previews and source collisions', () => {
  it('renders a real thumbnail and both source badges for a merged duplicate', () => {
    const thumbnail = 'data:image/jpeg;base64,thumbnail'
    const wrapper = mount(ModList, {
      props: {
        title: 'Mods',
        mods: [duplicateMod],
        thumbnails: { [duplicateMod.id]: thumbnail },
        typeMap: { overhaul: '大修' },
      },
    })

    const row = wrapper.get('.mod-row')
    expect(row.classes()).toContain('source-duplicate')
    expect(row.get('.mod-thumbnail img').attributes('src')).toBe(thumbnail)
    expect(row.find('.mod-sigil').exists()).toBe(false)
    expect(row.findAll('.source-badge').map(item => item.text())).toEqual(['游戏 DATA', 'STEAM 创意工坊'])
    expect(row.get('.row-subtitle').text()).toBe('same.pack')
    expect(row.get('.mod-author').text()).toBe('Example Author')
    expect(row.get('.mod-type-badge').text()).toBe('大修')
    expect(row.find('.workshop-id').exists()).toBe(false)
    expect(row.text()).not.toContain('#123')
  })

  it('emits the clicked mod and pointer coordinates for the custom context menu', async () => {
    const wrapper = mount(ModList, {
      props: { title: 'Mods', mods: [duplicateMod] },
    })

    await wrapper.get('.mod-row').trigger('contextmenu', { clientX: 321, clientY: 123 })

    expect(wrapper.emitted('context-menu')[0][0]).toMatchObject({
      x: 321,
      y: 123,
      mod: duplicateMod,
      active: false,
    })
  })

  it('marks visible hidden mods and exposes their warning text', () => {
    const wrapper = mount(ModList, {
      props: {
        title: 'Mods',
        mods: [{
          ...duplicateMod,
          hidden: true,
          warnings: [{ code: 'outdated', message: '需要检查兼容性' }],
        }],
      },
    })

    expect(wrapper.get('.mod-row').classes()).toContain('hidden-mod')
    expect(wrapper.get('.hidden-badge').text()).toBe('已隐藏')
    expect(wrapper.get('[data-testid="mod-warning-badge"]').attributes('title')).toContain('需要检查兼容性')
  })

  it('highlights matches, mutes nonmatches, and focuses the first result', async () => {
    const second = { ...duplicateMod, id: 'second', pack_name: 'second.pack' }
    const originalScrollIntoView = Element.prototype.scrollIntoView
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    try {
      const wrapper = mount(ModList, {
        props: {
          title: 'Mods',
          mods: [duplicateMod, second],
          searchActive: true,
          searchMatchIds: [second.id],
          searchFocusId: second.id,
        },
      })

      await nextTick()
      expect(wrapper.findAll('.mod-row')[0].classes()).toContain('search-muted')
      expect(wrapper.findAll('.mod-row')[1].classes()).toContain('search-match')
      expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'smooth' })
    } finally {
      Element.prototype.scrollIntoView = originalScrollIntoView
    }
  })

  it('emits modifier keys and the visible order for anchored multi-selection', async () => {
    const second = { ...duplicateMod, id: 'second', pack_name: 'second.pack' }
    const wrapper = mount(ModList, {
      props: { title: 'Mods', mods: [duplicateMod, second] },
    })

    await wrapper.findAll('.mod-row')[1].trigger('click', { ctrlKey: true, shiftKey: true })

    expect(wrapper.emitted('select')[0][0]).toEqual({
      id: 'second',
      ctrlKey: true,
      metaKey: false,
      shiftKey: true,
      orderedIds: [duplicateMod.id, 'second'],
    })
  })

  it('toggles only the double-clicked mod and ignores row action controls', async () => {
    const wrapper = mount(ModList, {
      props: {
        title: '已启用 MOD',
        active: true,
        mods: [duplicateMod],
        orderIds: [duplicateMod.id],
      },
    })

    await wrapper.get('.mod-row').trigger('dblclick')
    expect(wrapper.emitted('toggle-active')).toEqual([[duplicateMod.id]])

    await wrapper.get('.icon-button.danger').trigger('dblclick')
    expect(wrapper.emitted('toggle-active')).toHaveLength(1)
  })

  it('emits only the current visible list for Ctrl+A and leaves editable controls alone', async () => {
    const second = { ...duplicateMod, id: 'second', pack_name: 'second.pack' }
    const wrapper = mount(ModList, {
      props: { title: 'Mods', mods: [duplicateMod, second] },
    })

    await wrapper.get('[data-testid="mod-list"]').trigger('keydown', { key: 'a', ctrlKey: true })
    expect(wrapper.emitted('select-all')[0]).toEqual([[duplicateMod.id, 'second']])

    const input = document.createElement('input')
    wrapper.get('[data-testid="mod-list"]').element.appendChild(input)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, bubbles: true }))
    expect(wrapper.emitted('select-all')).toHaveLength(1)
  })

  it('renders missing dependencies as a red error badge', () => {
    const wrapper = mount(ModList, {
      props: {
        title: 'Mods',
        active: true,
        mods: [{
          ...duplicateMod,
          warnings: [{ code: 'missing_dependency', severity: 'error', message: '缺少依赖：base.pack' }],
        }],
      },
    })

    const badge = wrapper.get('[data-testid="mod-warning-badge"]')
    expect(badge.classes()).toContain('error')
    expect(badge.text()).toBe('! 缺少依赖')
  })

  it('does not show a stale missing-dependency badge in the inactive list', () => {
    const wrapper = mount(ModList, {
      props: {
        title: 'Mods',
        active: false,
        mods: [{
          ...duplicateMod,
          warnings: [{ code: 'missing_dependency', severity: 'error', message: '缺少依赖：base.pack' }],
        }],
      },
    })

    expect(wrapper.find('[data-testid="mod-warning-badge"]').exists()).toBe(false)
  })

  it('places the warning entry in the active-list heading and opens it on click', async () => {
    const wrapper = mount(ModList, {
      props: {
        title: '已启用 MOD',
        active: true,
        mods: [duplicateMod],
        warningCount: 3,
      },
    })

    const warningButton = wrapper.get('[data-testid="panel-warning-button"]')
    expect(warningButton.text()).toContain('3 条警告')
    await warningButton.trigger('click')
    expect(wrapper.emitted('show-warnings')).toHaveLength(1)
  })

  it('drags selected inactive mods together in their temporary order', async () => {
    const mods = ['b', 'c', 'd', 'e'].map(id => ({
      ...duplicateMod,
      id,
      pack_name: `${id}.pack`,
      effective_name: id.toUpperCase(),
    }))
    const wrapper = mount(ModList, {
      props: {
        title: '未启用 MOD',
        mods,
        selectedId: 'd',
        selectedIds: ['b', 'd'],
        orderIds: ['b', 'c', 'd', 'e'],
      },
    })
    const values = {}
    const dataTransfer = {
      effectAllowed: '',
      setData: vi.fn((type, value) => { values[type] = value }),
      getData: vi.fn(type => values[type] || ''),
    }
    const rows = wrapper.findAll('.mod-row')

    expect(rows[0].attributes('draggable')).toBe('true')
    await rows[0].trigger('dragstart', { dataTransfer })
    expect(rows[0].classes()).toContain('dragging')
    expect(rows[2].classes()).toContain('dragging')
    expect(dataTransfer.setData).toHaveBeenCalledWith('text/plain', 'b\nd')

    await rows[3].trigger('drop', { dataTransfer })
    expect(wrapper.emitted('drop-mods')[0][0]).toEqual({
      source: 'inactive',
      target: 'inactive',
      ids: ['b', 'd'],
      draggedId: 'b',
      sourceOrder: ['b', 'c', 'd', 'e'],
      targetId: 'e',
      targetOrder: ['b', 'c', 'd', 'e'],
    })
  })

  it('accepts a selected active batch dropped into the inactive list', async () => {
    const activeMods = ['a', 'b'].map(id => ({ ...duplicateMod, id, pack_name: `${id}.pack` }))
    const inactiveMods = ['c', 'd'].map(id => ({ ...duplicateMod, id, pack_name: `${id}.pack` }))
    const source = mount(ModList, {
      props: {
        title: '已启用 MOD',
        active: true,
        mods: activeMods,
        selectedId: 'b',
        selectedIds: ['a', 'b'],
        orderIds: ['a', 'b'],
      },
    })
    const target = mount(ModList, {
      props: { title: '未启用 MOD', mods: inactiveMods },
    })
    const values = {}
    const dataTransfer = {
      effectAllowed: '',
      setData: (type, value) => { values[type] = value },
      getData: type => values[type] || '',
    }

    await source.findAll('.mod-row')[0].trigger('dragstart', { dataTransfer })
    await target.findAll('.mod-row')[1].trigger('drop', { dataTransfer })

    expect(target.emitted('drop-mods')[0][0]).toMatchObject({
      source: 'active',
      target: 'inactive',
      ids: ['a', 'b'],
      targetId: 'd',
    })
  })
})
