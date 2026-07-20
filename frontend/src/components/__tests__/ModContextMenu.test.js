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
  it('puts manual type entry at the top of the type submenu with its shortcut', () => {
    const wrapper = mount(ModContextMenu, {
      props: { open: true, x: 100, y: 100, mod, active: true, types },
    })

    const submenu = wrapper.get('.type-submenu')
    expect(submenu.find('button').attributes('data-testid')).toBe('context-manual-type')
    expect(submenu.get('[data-testid="context-manual-type"] .context-menu-shortcut').text()).toBe('Shift + F')
  })

  it('shows configured shortcut keys beside shortcut actions', () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        mod,
        active: true,
        types,
        keyboardShortcuts: {
          'toggle-active': 'Ctrl+E',
          'open-workshop': 'Alt+W',
          'open-rpfm': 'Ctrl+Alt+R',
        },
      },
    })

    expect(wrapper.get('[data-testid="context-toggle-active"] .context-menu-shortcut').text()).toBe('Ctrl + E')
    expect(wrapper.get('[data-testid="context-open-workshop-browser"] .context-menu-shortcut').text()).toBe('Alt + W')
    expect(wrapper.get('[data-testid="context-open-rpfm"] .context-menu-shortcut').text()).toBe('Ctrl + Alt + R')
  })

  it('contains every requested operation and emits type selection', async () => {
    const wrapper = mount(ModContextMenu, {
      props: { open: true, x: 100, y: 100, mod, active: true, types },
    })

    for (const label of [
      '停用', '修改类型', '类型管理', '指定加载顺序', '列表顶部', '列表底部',
      '跳转到创意工坊', '跳转到创意工坊(客户端)', '取消订阅', '强制更新', '打开文件目录', '在 RPFM 打开', '从列表中隐藏',
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

  it('offers update for an eligible Workshop-only MOD and hides it for mismatched ownership', () => {
    const eligible = mount(ModContextMenu, {
      props: {
        open: true,
        mod,
        types,
        selectedModIds: [mod.id],
        eligibleUpdateIds: [mod.id],
      },
    })
    expect(eligible.find('[data-testid="context-publish-update"]').exists()).toBe(true)
    expect(eligible.find('[data-testid="context-publish-upload"]').exists()).toBe(false)

    const mismatched = mount(ModContextMenu, {
      props: {
        open: true,
        mod,
        types,
        selectedModIds: [mod.id],
        eligibleUpdateIds: [],
      },
    })
    expect(mismatched.find('[data-testid="context-publish-update"]').exists()).toBe(false)
  })

  it('hides update when any selected MOD is not eligible', () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        mod,
        types,
        selectionCount: 2,
        selectedModIds: [mod.id, 'steam:456:other.pack'],
        eligibleUpdateIds: [mod.id],
      },
    })

    expect(wrapper.find('[data-testid="context-publish-update"]').exists()).toBe(false)
  })

  it('offers AI generation only for an AI-configured batch selection', async () => {
    const wrapper = mount(ModContextMenu, {
      props: {
        open: true,
        mod,
        types,
        aiEnabled: true,
        selectionCount: 3,
      },
    })

    const action = wrapper.get('[data-testid="context-generate-user-data"]')
    expect(action.text()).toContain('AI生成（3项）')
    await action.trigger('click')
    expect(wrapper.emitted('action')[0][0]).toMatchObject({
      action: 'generate-user-data',
      mod,
    })

    await wrapper.setProps({ aiEnabled: false })
    expect(wrapper.find('[data-testid="context-generate-user-data"]').exists()).toBe(false)
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
        selectedModIds: [mod.id, 'steam:456:two.pack', 'steam:789:three.pack'],
        eligibleUpdateIds: [mod.id, 'steam:456:two.pack', 'steam:789:three.pack'],
      },
    })

    for (const label of [
      '停用（3项）', '修改类型（3项）', '移动到（3项）', 'Steam 操作（3项）',
      '忽略问题（3项）', '忽略 MOD 过期（3项）', '忽略缺失依赖（3项）',
      '打开文件目录（3项）', '从列表中隐藏（3项）', '复制模组到 Data 文件夹（3项）',
      'UI（3项）', '指定加载顺序（3项）', '列表顶部（3项）', '列表底部（3项）',
      '跳转到创意工坊（3项）', '跳转到创意工坊(客户端)（3项）', '取消订阅（3项）', '强制更新（3项）', '更新到工坊（3项）',
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

  it('places browser and client Workshop actions together at the top level', async () => {
    const wrapper = mount(ModContextMenu, {
      props: { open: true, x: 100, y: 100, mod, active: true, types },
    })

    const nav = wrapper.get('nav')
    const browser = buttonByText(wrapper, '跳转到创意工坊')
    const client = buttonByText(wrapper, '跳转到创意工坊(客户端)')
    const steamMenu = wrapper.get('[data-testid="context-steam-menu"]')
    expect(browser.element.parentElement).toBe(nav.element)
    expect(client.element.parentElement).toBe(nav.element)
    expect(client.element.previousElementSibling).toBe(browser.element)
    expect(steamMenu.element.previousElementSibling).toBe(client.element)
    expect(steamMenu.text()).not.toContain('跳转到创意工坊')

    await browser.trigger('click')
    await client.trigger('click')
    expect(wrapper.emitted('action')[0][0].action).toBe('open-workshop-browser')
    expect(wrapper.emitted('action')[1][0].action).toBe('open-workshop-client')
  })

  it('keeps the expanded top-level menu above the viewport bottom', () => {
    const originalHeight = window.innerHeight
    Object.defineProperty(window, 'innerHeight', { value: 760, configurable: true })
    try {
      const wrapper = mount(ModContextMenu, {
        props: { open: true, x: 100, y: 740, mod, active: true, types },
      })

      expect(wrapper.get('nav').attributes('style')).toContain('top: 212px')
    } finally {
      Object.defineProperty(window, 'innerHeight', { value: originalHeight, configurable: true })
    }
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
