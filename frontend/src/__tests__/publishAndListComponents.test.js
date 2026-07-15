// @vitest-environment jsdom

import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ModList from '../components/ModList.vue'
import WorkshopPublishModal from '../components/WorkshopPublishModal.vue'

const localMod = {
  id: 'local',
  effective_name: 'My Own Mod',
  display_name: 'My Own Mod',
  pack_name: 'my_own_mod.pack',
  path: 'G:/game/data/my_own_mod.pack',
  source: 'data',
  sources: ['data'],
  mod_types: ['units', 'ui'],
  workshop_id: '',
}

describe('visual-only list sorting guardrails', () => {
  it('shows all selected types and disables actual-order controls', () => {
    const wrapper = mount(ModList, {
      props: {
        title: '已启用 MOD',
        active: true,
        visualSorted: true,
        mods: [localMod],
        orderIds: ['local'],
        typeMap: { units: '单位', ui: 'UI' },
      },
    })
    expect(wrapper.findAll('.mod-type-badge').map(item => item.text())).toEqual(['单位', 'UI'])
    expect(wrapper.get('.mod-row').attributes('draggable')).toBe('false')
    const moveButtons = wrapper.findAll('.row-actions .icon-button').slice(0, 2)
    expect(moveButtons.every(button => button.attributes('disabled') !== undefined)).toBe(true)
  })
})

describe('Workshop publish confirmation', () => {
  it('requires explicit confirmation and emits data without contacting Steam', async () => {
    const wrapper = mount(WorkshopPublishModal, {
      global: { plugins: [createPinia()] },
      props: { open: true, mode: 'upload', mod: localMod, busy: '' },
    })
    const submit = wrapper.get('.primary-button')
    expect(submit.attributes('disabled')).toBeDefined()
    const inputs = wrapper.findAll('input')
    await inputs.find(input => input.attributes('type') === 'text' && !input.attributes('readonly'))
      .setValue('My Workshop Mod')
    await wrapper.get('.path-input-row input').setValue('G:/preview.png')
    await wrapper.get('.publish-confirmation input').setValue(true)
    expect(submit.attributes('disabled')).toBeUndefined()
    await submit.trigger('click')
    expect(wrapper.emitted('submit')[0][0]).toMatchObject({
      mode: 'upload',
      title: 'My Workshop Mod',
      preview_path: 'G:/preview.png',
      category: 'graphical',
      visibility: 0,
    })
  })
})
