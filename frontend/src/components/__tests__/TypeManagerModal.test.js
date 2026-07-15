import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import TypeManagerModal from '../TypeManagerModal.vue'

const types = [
  { id: 'ui', name: 'UI', built_in: true },
  { id: 'custom:audio', name: '音效', built_in: false },
]

describe('TypeManagerModal', () => {
  it('locks defaults and supports adding, editing, and deleting custom types', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(TypeManagerModal, { props: { open: true, types } })

    expect(wrapper.get('.type-manager-row.builtIn').text()).toContain('默认')
    expect(wrapper.findAll('.type-manager-row.builtIn input')).toHaveLength(0)

    const customInput = wrapper.get('input[aria-label="修改类型 音效"]')
    await customInput.setValue('音乐')
    await wrapper.findAll('button').find(button => button.text() === '保存').trigger('click')
    expect(wrapper.emitted('update')[0][0]).toEqual({ id: 'custom:audio', name: '音乐' })

    const createInput = wrapper.get('input[placeholder="输入新的自定义类型名称"]')
    await createInput.setValue('兼容补丁')
    await wrapper.get('.type-create-row').trigger('submit')
    expect(wrapper.emitted('create')[0][0]).toBe('兼容补丁')

    await wrapper.findAll('button').find(button => button.text() === '删除').trigger('click')
    expect(wrapper.emitted('delete')[0][0]).toBe('custom:audio')
    confirm.mockRestore()
  })
})
