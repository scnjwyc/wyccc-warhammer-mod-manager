import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WarningModal from '../WarningModal.vue'

const dependencyRefresh = {
  id: 'scan:workshop_dependency_refresh',
  modId: '',
  modName: '',
  code: 'workshop_dependency_refresh',
  severity: 'warning',
  message: 'Steam 暂时无法读取部分工坊依赖，已使用已有缓存；缺失依赖结果可能不是最新状态',
  ignorable: true,
}

const missingDependency = {
  dependencies: [{ kind: 'workshop', id: '123', name: 'Base Workshop Mod' }],
  id: 'mod-a:missing_dependency',
  modId: 'mod-a',
  modName: '测试 MOD',
  code: 'missing_dependency',
  severity: 'error',
  message: '缺少依赖：base.pack',
  ignorable: true,
}

describe('WarningModal', () => {
  it('opens as a modal and supports selecting or ignoring an individual MOD warning', async () => {
    const systemWarning = {
      id: 'scan:0',
      modId: '',
      modName: '',
      code: '',
      severity: 'warning',
      message: '扫描提示',
      ignorable: false,
    }
    const wrapper = mount(WarningModal, {
      props: { open: true, items: [missingDependency, dependencyRefresh, systemWarning] },
    })

    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.text()).toContain('共 3 条警告')
    expect(wrapper.text()).toContain('缺少依赖：base.pack')
    expect(wrapper.text()).toContain('缺失依赖结果可能不是最新状态')
    expect(wrapper.findAll('.warning-ignore-button')).toHaveLength(2)

    const ignoreButtons = wrapper.findAll('.warning-ignore-button')
    await ignoreButtons[0].trigger('click')
    await ignoreButtons[1].trigger('click')
    expect(wrapper.emitted('ignore')[0][0]).toEqual(missingDependency)
    expect(wrapper.emitted('ignore')[1][0]).toEqual(dependencyRefresh)

    await wrapper.get('.warning-subscribe-button').trigger('click')
    expect(wrapper.emitted('subscribe-enable')[0][0]).toEqual(missingDependency)

    await wrapper.get('button.warning-modal-copy').trigger('click')
    expect(wrapper.emitted('select')[0][0]).toEqual(missingDependency)
  })

  it('shows a resolved state after the last visible warning is ignored', () => {
    const wrapper = mount(WarningModal, {
      props: { open: true, items: [] },
    })

    expect(wrapper.text()).toContain('当前没有未忽略的问题')
  })

  it('labels a Workshop update and allows it to be ignored', async () => {
    const wrapper = mount(WarningModal, {
      props: {
        open: true,
        items: [{
          id: 'mod-a:workshop_update_available',
          modId: 'mod-a',
          modName: '测试 MOD',
          code: 'workshop_update_available',
          severity: 'warning',
          message: 'Steam 创意工坊信息显示该 MOD 有新更新，请在工坊中确认并更新',
          ignorable: true,
        }],
      },
    })

    expect(wrapper.get('.warning-modal-type').text()).toBe('MOD 有新更新')
    await wrapper.get('.warning-ignore-button').trigger('click')
    expect(wrapper.emitted('ignore')[0][0]).toMatchObject({
      code: 'workshop_update_available',
      modId: 'mod-a',
    })
  })

  it('offers a per-MOD update button only for Workshop update-available warnings', async () => {
    const updateItem = {
      id: 'mod-a:workshop_update_available',
      modId: 'mod-a',
      modName: '测试 MOD',
      code: 'workshop_update_available',
      severity: 'warning',
      message: 'Steam 创意工坊信息显示该 MOD 有新更新，请在工坊中确认并更新',
      ignorable: true,
    }
    const outdatedItem = {
      id: 'mod-b:outdated_mod',
      modId: 'mod-b',
      modName: '过期 MOD',
      code: 'outdated_mod',
      severity: 'warning',
      message: '该 MOD 在游戏本体更新后尚未更新',
      ignorable: true,
    }
    const wrapper = mount(WarningModal, {
      props: { open: true, items: [updateItem, outdatedItem, dependencyRefresh] },
    })

    expect(wrapper.findAll('.warning-update-button')).toHaveLength(1)
    await wrapper.get('.warning-update-button').trigger('click')
    expect(wrapper.emitted('update')[0][0]).toEqual(updateItem)
  })

  it('enables the bottom-left update-all button only when a Workshop update is available', async () => {
    const updateItem = {
      id: 'mod-a:workshop_update_available',
      modId: 'mod-a',
      modName: '测试 MOD',
      code: 'workshop_update_available',
      severity: 'warning',
      message: 'Steam 创意工坊信息显示该 MOD 有新更新，请在工坊中确认并更新',
      ignorable: true,
    }
    const withoutUpdates = mount(WarningModal, {
      props: { open: true, items: [missingDependency, dependencyRefresh] },
    })
    expect(withoutUpdates.get('.warning-update-all-button').element.disabled).toBe(true)

    const wrapper = mount(WarningModal, {
      props: { open: true, items: [missingDependency, updateItem] },
    })
    expect(wrapper.get('.warning-update-all-button').element.disabled).toBe(false)
    await wrapper.get('.warning-update-all-button').trigger('click')
    expect(wrapper.emitted('update-all')).toHaveLength(1)
  })
})
