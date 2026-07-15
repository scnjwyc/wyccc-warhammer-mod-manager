import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import SettingsModal from '../SettingsModal.vue'
import {
  LANGUAGE_OPTIONS,
  applyInterfaceLanguage,
  contentLanguageFor,
  normalizeLanguage,
} from '../../languages'

describe('language settings', () => {
  it('offers and saves all five supported language selections', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: { language: 'ko-KR' },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })
    const select = wrapper.get('[data-testid="language-select"]')

    expect(select.findAll('option').map(option => [option.attributes('value'), option.text()])).toEqual(
      LANGUAGE_OPTIONS.map(language => [language.code, language.label]),
    )
    expect(select.element.value).toBe('ko-KR')

    await select.setValue('ru-RU')
    await wrapper.get('.primary-button').trigger('click')

    expect(wrapper.emitted('save')[0][0].language).toBe('ru-RU')
  })

  it('saves AI, outdated checks and all three game launch options', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: {
          language: 'zh-CN',
          ai_enabled: false,
          ai_base_url: 'https://api.openai.com/v1',
          ai_model: '',
          ai_temperature: 0.3,
          check_outdated_mods: false,
          custom_battle_all_units_as_lords: false,
          enable_script_logging: false,
          skip_intro_movies: false,
        },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    await wrapper.get('[data-testid="ai-enabled"]').setValue(true)
    await wrapper.get('[data-testid="ai-model"]').setValue('example-model')
    await wrapper.get('[data-testid="check-outdated-mods"]').setValue(true)
    await wrapper.get('[data-testid="all-units-as-lords"]').setValue(true)
    await wrapper.get('[data-testid="script-logging"]').setValue(true)
    await wrapper.get('[data-testid="skip-intro-movies"]').setValue(true)
    await wrapper.get('.primary-button').trigger('click')

    expect(wrapper.emitted('save')[0][0]).toMatchObject({
      ai_enabled: true,
      ai_model: 'example-model',
      check_outdated_mods: true,
      custom_battle_all_units_as_lords: true,
      enable_script_logging: true,
      skip_intro_movies: true,
    })
    expect(wrapper.text()).toContain('先结合标题总结原简介，再翻译为当前设置语言')
    expect(wrapper.text()).toContain('优先复用本地战锤术语库')
    expect(wrapper.text()).toContain('未命中时由 AI 根据原文直接翻译')
    expect(wrapper.text()).toContain('不联网搜索、不查询原版 LOC')
    expect(wrapper.text()).toContain('扫描固定覆盖游戏 Data 与 Steam Workshop')
    expect(wrapper.text()).not.toContain('RPFM 可执行文件')
    expect(wrapper.text()).not.toContain('Modding 目录')
    expect(wrapper.text()).not.toContain('Merged 目录')
  })

  it('keeps Chinese as the current content language for every selection', () => {
    for (const language of LANGUAGE_OPTIONS) {
      expect(contentLanguageFor(language.code)).toBe('zh-CN')
    }
    expect(normalizeLanguage('unknown')).toBe('zh-CN')

    expect(applyInterfaceLanguage('ja-JP')).toBe('ja-JP')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(document.documentElement.dataset.selectedLanguage).toBe('ja-JP')
    expect(document.documentElement.dataset.contentLanguage).toBe('zh-CN')
  })

  it('exposes automatic checks, the manifest channel and changelog actions', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: {
          language: 'zh-CN',
          check_updates_automatically: true,
          update_manifest_url: 'https://updates.example.test/manifest.json',
        },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    await wrapper.get('[data-testid="auto-update-check"]').setValue(false)
    await wrapper.get('[data-testid="update-manifest-url"]').setValue('https://cdn.example.test/latest.json')
    await wrapper.get('.update-check-button').trigger('click')
    expect(wrapper.emitted('check-update')[0][0]).toBe('https://cdn.example.test/latest.json')

    const changelogButton = wrapper.findAll('button').find(button => button.text() === '更新日志')
    await changelogButton.trigger('click')
    expect(wrapper.emitted('show-changelog')).toHaveLength(1)

    await wrapper.get('.modal-footer .primary-button').trigger('click')
    expect(wrapper.emitted('save')[0][0]).toMatchObject({
      check_updates_automatically: false,
      update_manifest_url: 'https://cdn.example.test/latest.json',
    })
  })
})
