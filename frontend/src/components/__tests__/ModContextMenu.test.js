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
  ignored_warning_codes: [],
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
      '访问创意工坊', '取消订阅', '强制更新', '打开文件目录', '在 RPFM 打开', '从列表中隐藏',
      '复制 MOD 路径', '删除 MOD 文件', '复制模组到 Data 文件夹',
      '忽略问题', '忽略 MOD 过期', '忽略缺失依赖',
    ]) {
      expect(wrapper.text()).toContain(label)
    }

    await buttonByText(wrapper, '音效').trigger('click')
    expect(wrapper.emitted('action')[0][0]).toMatchObject({ action: 'toggle-type', value: 'custom:audio', mod })
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('labels a merged deletion as Data-only and blocks destructive actions while the game runs', () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        mod: { ...mod, source: 'data', sources: ['data', 'workshop'] },
        types,
        gameRunning: true,
      },
    })

    expect(buttonByText(wrapper, '从 DATA 中删除').attributes('disabled')).toBeDefined()
    expect(buttonByText(wrapper, '取消订阅').attributes('disabled')).toBeDefined()
  })

  it('shows batch counts on top-level actions and disables the RPFM action', async () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        x: 100,
        y: 100,
        mod: { ...mod, sources: ['data', 'workshop'] },
        active: true,
        types,
        selectionCount: 3,
      },
    })

    for (const label of [
      '停用（3项）', '修改类型（3项）', '移动到（3项）', 'Steam 操作（3项）',
      '忽略问题（3项）', '忽略 MOD 过期（3项）', '忽略缺失依赖（3项）',
      '打开文件目录（3项）', '从列表中隐藏（3项）', '复制模组到 Data 文件夹（3项）',
      'UI（3项）', '指定加载顺序（3项）', '列表顶部（3项）', '列表底部（3项）',
      '访问创意工坊（3项）', '取消订阅（3项）', '强制更新（3项）', '更新到工坊（3项）',
    ]) {
      expect(wrapper.text()).toContain(label)
    }

    const rpfm = wrapper.get('[data-testid="context-open-rpfm"]')
    expect(rpfm.attributes('disabled')).toBeDefined()
    expect(rpfm.attributes('title')).toContain('批量选择')
    expect(rpfm.text()).toContain('仅限单项')
    expect(rpfm.text()).not.toContain('3项')

    await buttonByText(wrapper, '打开文件目录').trigger('click')
    expect(wrapper.emitted('action')[0][0]).toMatchObject({ action: 'open-folder', mod: { id: mod.id } })
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

  it('toggles persistent warning categories and shows ignored state', async () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        mod: { ...mod, ignored_warning_codes: ['missing_dependency'] },
        types,
      },
    })

    const missingDependency = buttonByText(wrapper, '忽略缺失依赖')
    expect(missingDependency.attributes('aria-checked')).toBe('true')
    expect(missingDependency.classes()).toContain('checked')

    await buttonByText(wrapper, '忽略 MOD 过期').trigger('click')
    expect(wrapper.emitted('action')[0][0]).toMatchObject({
      action: 'toggle-warning-ignore',
      value: 'outdated_mod',
      mod: { id: mod.id },
    })
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('keeps submenu parents hover-only instead of making them clickable or focusable', async () => {
    const wrapper = mount(ModContextMenu, {
      props: { open: true, x: 100, y: 100, mod, active: true, types },
    })

    for (const testId of [
      'context-type-menu',
      'context-move-menu',
      'context-steam-menu',
      'context-ignore-warning-menu',
    ]) {
      const parent = wrapper.get(`[data-testid="${testId}"]`)
      expect(parent.attributes('tabindex')).toBeUndefined()
      expect(parent.element.tagName).toBe('DIV')
      await parent.trigger('click')
    }

    expect(wrapper.emitted('action')).toBeUndefined()
    expect(wrapper.emitted('close')).toBeUndefined()
  })
})
