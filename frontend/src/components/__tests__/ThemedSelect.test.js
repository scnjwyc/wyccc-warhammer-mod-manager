import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import ThemedSelect from '../ThemedSelect.vue'

const componentSource = readFileSync(
  resolve(process.cwd(), 'src/components/ThemedSelect.vue'),
  'utf8',
)

const options = [
  { value: 'default', label: '默认' },
  { value: 'one', label: '1' },
  { value: 'two', label: '2' },
]

describe('themed select', () => {
  it('renders and selects options without a native select popup', async () => {
    const wrapper = mount(ThemedSelect, {
      props: {
        modelValue: 'one',
        options,
        ariaLabel: '播放集',
      },
    })

    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.get('.themed-select-trigger').attributes('role')).toBe('combobox')
    expect(wrapper.get('.themed-select-value').text()).toBe('1')

    await wrapper.get('.themed-select-trigger').trigger('click')

    expect(wrapper.get('.themed-select-menu').attributes('role')).toBe('listbox')
    expect(wrapper.findAll('.themed-select-option').map(option => option.text())).toEqual(['默认', '1', '2'])
    expect(wrapper.get('[data-value="one"]').attributes('aria-selected')).toBe('true')

    await wrapper.get('[data-value="two"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([['two']])
    expect(wrapper.emitted('change')).toEqual([['two']])
    expect(wrapper.find('.themed-select-menu').exists()).toBe(false)
  })

  it('supports keyboard selection and respects the disabled state', async () => {
    const wrapper = mount(ThemedSelect, {
      props: {
        modelValue: 'one',
        options,
      },
    })
    const trigger = wrapper.get('.themed-select-trigger')

    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await trigger.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('update:modelValue')).toEqual([['two']])

    await wrapper.setProps({ disabled: true })
    await trigger.trigger('click')
    expect(trigger.attributes()).toHaveProperty('disabled')
    expect(wrapper.find('.themed-select-menu').exists()).toBe(false)
  })

  it('does not paint a gold strip before the selected option', () => {
    const selectedRule = componentSource.match(/\.themed-select-option\.selected\s*\{([^}]*)\}/)?.[1] ?? ''

    expect(selectedRule).not.toContain('inset 3px 0 0 var(--gold)')
  })
})
