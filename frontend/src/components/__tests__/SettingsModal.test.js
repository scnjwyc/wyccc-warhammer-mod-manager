import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it } from 'vitest'

import SettingsModal from '../SettingsModal.vue'
import {
  LANGUAGE_OPTIONS,
  applyInterfaceLanguage,
  contentLanguageFor,
  languageLabel,
  normalizeLanguage,
} from '../../languages'

afterEach(() => applyInterfaceLanguage('zh-CN'))

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
      LANGUAGE_OPTIONS.map(language => [language.code, languageLabel(language)]),
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
    expect(wrapper.text()).toContain('过期MOD仅代表该MOD在游戏本体更新后未更新，不代表这个MOD无法使用')
    expect(wrapper.text()).toContain('MOD 扫描覆盖游戏 Data 与 STEAM 创意工坊')
    expect(wrapper.text()).not.toContain('RPFM 可执行文件')
    expect(wrapper.text()).not.toContain('Modding 目录')
    expect(wrapper.text()).not.toContain('Merged 目录')
  })

  it('uses the selected language as the content language', () => {
    for (const language of LANGUAGE_OPTIONS) {
      expect(contentLanguageFor(language.code)).toBe(language.code)
    }
    expect(normalizeLanguage('unknown')).toBe('en-US')

    expect(applyInterfaceLanguage('ja-JP')).toBe('ja-JP')
    expect(document.documentElement.lang).toBe('ja-JP')
    expect(document.documentElement.dataset.selectedLanguage).toBe('ja-JP')
    expect(document.documentElement.dataset.contentLanguage).toBe('ja-JP')
    applyInterfaceLanguage('zh-CN')
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
    expect(wrapper.text()).toContain('中文优先使用 Gitee，其他语言优先使用 GitHub')
    expect(wrapper.text()).toContain('两个仓库都会检查')

    const changelogButton = wrapper.findAll('button').find(button => button.text() === '更新日志')
    await changelogButton.trigger('click')
    expect(wrapper.emitted('show-changelog')).toHaveLength(1)

    await wrapper.get('.modal-footer .primary-button').trigger('click')
    expect(wrapper.emitted('save')[0][0]).toMatchObject({
      check_updates_automatically: false,
      update_manifest_url: 'https://cdn.example.test/latest.json',
    })
  })

  it('allows checking both built-in repositories with an empty custom channel', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: {
          language: 'zh-CN',
          check_updates_automatically: true,
          update_manifest_url: '',
        },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    const button = wrapper.get('.update-check-button')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')

    expect(wrapper.emitted('check-update')[0][0]).toBe('')
    expect(wrapper.get('[data-testid="update-manifest-url"]').attributes('placeholder')).toContain('Gitee 与 GitHub')
  })

  it('splits settings into four pages and exposes the project support page', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: { language: 'zh-CN' },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    expect(wrapper.findAll('.settings-tab-button').map(button => button.text())).toEqual([
      expect.stringContaining('基础设置'),
      expect.stringContaining('功能'),
      expect.stringContaining('AI 集成'),
      expect.stringContaining('关于项目'),
    ])
    await wrapper.get('[data-testid="settings-tab-about"]').trigger('click')
    expect(wrapper.get('[data-testid="settings-page-about"]').isVisible()).toBe(true)
    expect(wrapper.text()).toContain('GitHub 发布页')
    expect(wrapper.text()).toContain('Gitee 发布页')
    expect(wrapper.text()).toContain('QQ群')
    expect(wrapper.text()).toContain('592799189')
    expect(wrapper.text()).not.toContain('Gitee Issues')
    expect(wrapper.text()).not.toContain('GitHub 仓库')
    expect(wrapper.text()).not.toContain('Gitee 仓库')
    expect(wrapper.text()).not.toContain('蓝奏云')
    expect(wrapper.text()).not.toContain('贴吧主帖')
    expect(wrapper.text()).not.toContain('参考项目')
    expect(wrapper.findAll('.about-card')[0].findAll('strong').map(item => item.text())).toEqual([
      'GitHub 发布页',
      'Gitee 发布页',
    ])
    expect(wrapper.findAll('.about-card')[1].findAll('strong').map(item => item.text())).toEqual([
      'GitHub Issues',
      'QQ群',
    ])
    const qqGroup = wrapper.get('[data-testid="feedback-qq-group"]')
    expect(qqGroup.findAll('button')).toHaveLength(1)
    expect(qqGroup.get('button').attributes('title')).toBe('复制群号')

    const donationButton = wrapper.findAll('button').find(button => button.text() === '查看收款码')
    await donationButton.trigger('click')
    const donationImage = document.body.querySelector('.donation-modal img')
    expect(donationImage?.getAttribute('src')).toContain('donate-qr.jpg')
    wrapper.unmount()
  })
})
