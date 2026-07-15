import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WarningModal from '../WarningModal.vue'

const missingDependency = {
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
      props: { open: true, items: [missingDependency, systemWarning] },
    })

    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.text()).toContain('共 2 条警告')
    expect(wrapper.text()).toContain('缺少依赖：base.pack')
    expect(wrapper.findAll('.warning-ignore-button')).toHaveLength(1)

    await wrapper.get('.warning-ignore-button').trigger('click')
    expect(wrapper.emitted('ignore')[0][0]).toEqual(missingDependency)

    await wrapper.get('button.warning-modal-copy').trigger('click')
    expect(wrapper.emitted('select')[0][0]).toEqual(missingDependency)
  })

  it('shows a resolved state after the last visible warning is ignored', () => {
    const wrapper = mount(WarningModal, {
      props: { open: true, items: [] },
    })

    expect(wrapper.text()).toContain('当前没有未忽略的问题')
  })
})
