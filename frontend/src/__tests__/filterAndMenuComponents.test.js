// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ModContextMenu from '../components/ModContextMenu.vue'
import SortMenu from '../components/SortMenu.vue'
import TagSearchBox from '../components/TagSearchBox.vue'

const types = [
  { id: 'language', name: '语言包', built_in: true },
  { id: 'ui', name: 'UI', built_in: true },
  { id: 'unknown', name: '未知', built_in: true },
]

describe('tag search input', () => {
  it('commits multiple removable tokens and switches AND/OR logic', async () => {
    const wrapper = mount(TagSearchBox, {
      props: { tokens: [], logic: 'AND', mods: [], typeMap: {} },
    })
    const input = wrapper.get('input')
    await input.setValue('author:Wyccc')
    await input.trigger('keydown', { key: 'Enter' })
    const firstTokens = wrapper.emitted('update:tokens')[0][0]
    await wrapper.setProps({ tokens: firstTokens })
    await input.setValue('type:UI')
    await input.trigger('keydown', { key: 'Enter' })

    const secondTokens = wrapper.emitted('update:tokens')[1][0]
    expect(secondTokens).toHaveLength(2)
    expect(secondTokens.map(token => token.key)).toEqual(['author', 'type'])
    await wrapper.setProps({ tokens: secondTokens })

    await wrapper.get('.search-logic-button').trigger('click')
    expect(wrapper.emitted('update:logic')[0]).toEqual(['OR'])
    await wrapper.get('.search-token button').trigger('click')
    expect(wrapper.emitted('update:tokens').at(-1)[0]).toHaveLength(1)
  })

  it('suggests configured MOD types', async () => {
    const wrapper = mount(TagSearchBox, {
      props: { tokens: [], mods: [], typeMap: { language: '语言包', ui: 'UI' } },
    })
    await wrapper.get('input').setValue('type:语')
    expect(wrapper.text()).toContain('语言包')
  })
})

describe('display sort control', () => {
  it('offers every requested field and states that it is display-only', async () => {
    const wrapper = mount(SortMenu, { props: { mode: 'priority', descending: false } })
    await wrapper.get('[data-testid="sort-button"]').trigger('click')
    expect(wrapper.text()).toContain('优先级')
    expect(wrapper.text()).toContain('文件名')
    expect(wrapper.text()).toContain('模组名')
    expect(wrapper.text()).toContain('作者')
    expect(wrapper.text()).toContain('更新时间')
    expect(wrapper.text()).toContain('创建时间')
    expect(wrapper.text()).toContain('仅改变列表显示，不修改实际加载顺序')
  })
})

describe('MOD context menu', () => {
  it('keeps the menu open while toggling multiple types', async () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        x: 20,
        y: 20,
        active: false,
        types,
        mod: {
          id: 'local',
          path: 'G:/game/data/local.pack',
          source: 'data',
          sources: ['data'],
          mod_type: 'language',
          mod_types: ['language', 'ui'],
          workshop_id: '',
        },
      },
    })
    const checkboxes = wrapper.findAll('[role="menuitemcheckbox"]')
    expect(checkboxes.map(item => item.attributes('aria-checked'))).toEqual(['true', 'true', 'false'])
    await checkboxes[1].trigger('click')
    expect(wrapper.emitted('action')[0][0]).toMatchObject({ action: 'toggle-type', value: 'ui' })
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(wrapper.text()).toContain('上传到工坊')
  })

  it('offers Workshop update for a local mod with an existing Workshop ID', () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        x: 20,
        y: 20,
        types,
        mod: {
          id: 'published',
          path: 'G:/game/data/published.pack',
          source: 'data',
          sources: ['data'],
          mod_types: ['ui'],
          workshop_id: '123456',
        },
      },
    })
    expect(wrapper.text()).toContain('更新到工坊')
    expect(wrapper.text()).not.toContain('上传到工坊')
  })
})
