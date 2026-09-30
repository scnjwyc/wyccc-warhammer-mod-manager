import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import FolderNameModal from '../FolderNameModal.vue'

const render = props => mount(FolderNameModal, {
  props: { open: true, ...props }, global: { stubs: { teleport: true } }, attachTo: document.body,
})

describe('folder name dialog', () => {
  it('focuses the name, rejects empty or oversized names and submits a trimmed name', async () => {
    const wrapper = render({})
    try {
      await nextTick()
      const input = wrapper.get('input')
      expect(document.activeElement).toBe(input.element)
      expect(wrapper.get('button[type="submit"]').element.disabled).toBe(true)
      await input.setValue('x'.repeat(81))
      await wrapper.get('form').trigger('submit')
      expect(wrapper.emitted('submit')).toBeUndefined()
      await input.setValue('  界面与汉化  ')
      await wrapper.get('form').trigger('submit')
      expect(wrapper.emitted('submit')[0]).toEqual(['界面与汉化'])
    } finally { wrapper.unmount() }
  })

  it('prefills renamed folders, displays save errors and stays open while saving', async () => {
    const wrapper = render({ rename: true, initialName: 'UI', error: '同名文件夹已存在' })
    try {
      await nextTick()
      expect(wrapper.get('input').element.value).toBe('UI')
      expect(wrapper.get('[role="alert"]').text()).toBe('同名文件夹已存在')
      await wrapper.setProps({ busy: true })
      await wrapper.get('form').trigger('submit')
      await wrapper.get('form').trigger('keydown', { key: 'Escape' })
      expect(wrapper.emitted('submit')).toBeUndefined()
      expect(wrapper.emitted('close')).toBeUndefined()
      await wrapper.setProps({ busy: false })
      await wrapper.get('form').trigger('keydown', { key: 'Escape' })
      expect(wrapper.emitted('close')).toHaveLength(1)
    } finally { wrapper.unmount() }
  })

  it('keeps Tab focus within the dialog', async () => {
    const wrapper = render({ initialName: 'UI' })
    try {
      await nextTick()
      const buttons = wrapper.findAll('button')
      buttons.at(-1).element.focus()
      await wrapper.get('form').trigger('keydown', { key: 'Tab' })
      expect(document.activeElement).toBe(buttons[0].element)
      await wrapper.get('form').trigger('keydown', { key: 'Tab', shiftKey: true })
      expect(document.activeElement).toBe(buttons.at(-1).element)
    } finally { wrapper.unmount() }
  })
})
