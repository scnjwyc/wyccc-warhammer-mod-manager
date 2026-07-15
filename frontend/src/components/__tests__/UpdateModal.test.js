import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import UpdateModal from '../UpdateModal.vue'


const updateInfo = {
  current_version: '0.1.0',
  version: '0.2.0',
  published_at: '2026-07-15',
  size: 12 * 1024 * 1024,
  status: 'remote',
  entries: [
    {
      title: '本次更新',
      changes: [
        { type: 'feature', text: '新增自动更新。' },
        { type: 'fix', text: '修复启动问题。' },
      ],
    },
  ],
}


describe('software update modal', () => {
  it('shows release notes and changes from download to verified install action', async () => {
    const wrapper = mount(UpdateModal, {
      props: { open: true, mode: 'update', info: updateInfo },
    })

    expect(wrapper.text()).toContain('发现新版本 v0.2.0')
    expect(wrapper.text()).toContain('新增自动更新。')
    expect(wrapper.text()).toContain('12.0 MB')
    await wrapper.get('.primary-button').trigger('click')
    expect(wrapper.emitted('download')).toHaveLength(1)

    await wrapper.setProps({ info: { ...updateInfo, status: 'ready' } })
    expect(wrapper.text()).toContain('SHA-256 已校验')
    await wrapper.get('.primary-button').trigger('click')
    expect(wrapper.emitted('install')).toHaveLength(1)
  })

  it('renders the local changelog timeline', () => {
    const wrapper = mount(UpdateModal, {
      props: {
        open: true,
        mode: 'changelog',
        changelog: [
          {
            version: '0.1.0',
            date: '2026-07-15',
            entries: updateInfo.entries,
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('更新日志')
    expect(wrapper.text()).toContain('v0.1.0')
    expect(wrapper.text()).toContain('修复启动问题。')
  })
})
