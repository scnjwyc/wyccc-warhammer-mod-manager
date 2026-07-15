import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ModContextMenu from '../ModContextMenu.vue'

const mod = {
  id: 'steam:123:example.pack',
  effective_name: 'Example',
  path: 'X:/workshop/123/example.pack',
  source: 'workshop',
  sources: ['workshop'],
  workshop_id: '123',
  mod_type: 'ui',
  mod_types: ['ui'],
  hidden: false,
}

const types = [
  { id: 'ui', name: 'UI', built_in: true },
  { id: 'unknown', name: '未知', built_in: true },
  { id: 'custom:audio', name: '音效', built_in: false },
]

const buttonByText = (wrapper, text) => wrapper.findAll('button').find(button => button.text().includes(text))

describe('ModContextMenu', () => {
  it('contains every requested operation and emits type selection', async () => {
    const wrapper = mount(ModContextMenu, {
      props: { open: true, x: 100, y: 100, mod, active: true, types },
    })

    for (const label of [
      '停用', '修改类型', '类型管理', '指定加载顺序', '列表顶部', '列表底部',
      '访问创意工坊', '取消订阅', '强制更新', '在 RPFM 打开', '从列表中隐藏',
      '复制模组到 Data 文件夹',
    ]) {
      expect(wrapper.text()).toContain(label)
    }

    await buttonByText(wrapper, '音效').trigger('click')
    expect(wrapper.emitted('action')[0][0]).toMatchObject({ action: 'toggle-type', value: 'custom:audio', mod })
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('disables copying when the merged entry already exists in Data', () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        mod: { ...mod, source: 'data', sources: ['data', 'workshop'] },
        types,
      },
    })

    expect(buttonByText(wrapper, '复制模组到 Data 文件夹').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('已在 Data')
  })

  it('visibly labels unavailable parent actions', () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        mod: { ...mod, source: 'workshop', sources: ['workshop'], workshop_id: '' },
        active: false,
        types,
      },
    })

    expect(wrapper.get('[data-testid="context-move-menu"]').text()).toContain('不可用')
    expect(wrapper.get('[data-testid="context-steam-menu"]').text()).toContain('不可用')
  })

  it('keeps submenu parents hover-only instead of making them clickable or focusable', async () => {
    const wrapper = mount(ModContextMenu, {
      props: { open: true, x: 100, y: 100, mod, active: true, types },
    })

    for (const testId of ['context-type-menu', 'context-move-menu', 'context-steam-menu']) {
      const parent = wrapper.get(`[data-testid="${testId}"]`)
      expect(parent.attributes('tabindex')).toBeUndefined()
      expect(parent.element.tagName).toBe('DIV')
      await parent.trigger('click')
    }

    expect(wrapper.emitted('action')).toBeUndefined()
    expect(wrapper.emitted('close')).toBeUndefined()
  })
})
