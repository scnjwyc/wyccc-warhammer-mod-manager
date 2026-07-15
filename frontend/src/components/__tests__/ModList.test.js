import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

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
    expect(row.findAll('.source-badge').map(item => item.text())).toEqual(['DATA', 'WORKSHOP'])
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

  it('renders missing dependencies as a red error badge', () => {
    const wrapper = mount(ModList, {
      props: {
        title: 'Mods',
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
})
