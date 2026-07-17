// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ModList from '../components/ModList.vue'
import WorkshopPublishModal from '../components/WorkshopPublishModal.vue'
import { useAppStore } from '../store'

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
    expect(wrapper.get('.mod-row').attributes('draggable')).toBe('true')
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
    expect(wrapper.get('[data-testid="publish-cover-path"]').element.value)
      .toBe('G:/game/data/my_own_mod.png')
    expect(wrapper.find('.path-input-row').exists()).toBe(false)
    await wrapper.get('input[type="text"][maxlength="128"]').setValue('My Workshop Mod')
    await wrapper.get('.publish-confirmation input').setValue(true)
    expect(submit.attributes('disabled')).toBeUndefined()
    await submit.trigger('click')
    expect(wrapper.emitted('submit')[0][0]).toMatchObject({
      mode: 'upload',
      title: 'My Workshop Mod',
      language: 'en-US',
      category: 'graphical',
      visibility: 0,
    })
    expect(wrapper.emitted('submit')[0][0]).not.toHaveProperty('preview_path')
  })

  it('defaults to English when only English description exists and reloads selected languages', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAppStore()
    store.settings = { language: 'zh-CN' }
    store.loadWorkshopPublishCopy = vi.fn()
      .mockResolvedValueOnce({
        title: '中文标题',
        description: 'English description',
        suggested_language: 'en-US',
        effective_language: 'en-US',
      })
      .mockResolvedValueOnce({
        title: 'English title',
        description: 'English description',
        suggested_language: 'en-US',
        effective_language: 'en-US',
      })
      .mockResolvedValueOnce({
        title: 'Русский заголовок',
        description: 'Русское описание',
        suggested_language: 'ru-RU',
        effective_language: 'ru-RU',
      })
    const wrapper = mount(WorkshopPublishModal, {
      global: { plugins: [pinia] },
      props: {
        open: true,
        mode: 'update',
        mod: { ...localMod, workshop_id: '123', preview_path: 'G:/preview.png' },
        busy: '',
      },
    })

    await flushPromises()
    await flushPromises()
    const language = wrapper.get('[data-testid="publish-language-select"]')
    expect(language.element.value).toBe('en-US')
    expect(wrapper.get('input[type="text"][maxlength="128"]').element.value).toBe('English title')
    expect(wrapper.text()).toContain('更新日志')
    expect(wrapper.find('textarea[rows="3"]').element.value).toBe('')

    await language.setValue('ru-RU')
    await flushPromises()
    expect(wrapper.get('input[type="text"][maxlength="128"]').element.value).toBe('Русский заголовок')
    expect(wrapper.find('textarea[rows="6"]').element.value).toBe('Русское описание')

    await wrapper.get('.publish-confirmation input').setValue(true)
    await wrapper.get('.primary-button').trigger('click')
    expect(wrapper.emitted('submit')[0][0]).toMatchObject({
      mode: 'update',
      language: 'ru-RU',
      title: 'Русский заголовок',
      description: 'Русское описание',
      change_note: '',
    })
    expect(store.loadWorkshopPublishCopy.mock.calls).toEqual([
      ['local', 'zh-CN'],
      ['local', 'en-US'],
      ['local', 'ru-RU'],
    ])
  })
})
