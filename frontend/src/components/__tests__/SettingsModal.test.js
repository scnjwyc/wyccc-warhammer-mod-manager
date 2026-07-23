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
  it('offers and saves all six supported language selections', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: { language: 'ko-KR' },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })
    const select = wrapper.get('[data-testid="language-select"]')

    await select.get('.themed-select-trigger').trigger('click')
    expect(select.findAll('.themed-select-option').map(option => [option.attributes('data-value'), option.text()])).toEqual(
      LANGUAGE_OPTIONS.map(language => [language.code, languageLabel(language)]),
    )
    expect(select.get('.themed-select-value').text()).toBe(languageLabel(LANGUAGE_OPTIONS.find(language => language.code === 'ko-KR')))

    await select.get('[data-value="es-ES"]').trigger('click')
    await wrapper.get('.primary-button').trigger('click')

    expect(wrapper.emitted('save')[0][0].language).toBe('es-ES')
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
          live_mod_detection: true,
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
    await wrapper.get('[data-testid="live-mod-detection"]').setValue(false)
    await wrapper.get('[data-testid="all-units-as-lords"]').setValue(true)
    await wrapper.get('[data-testid="script-logging"]').setValue(true)
    await wrapper.get('[data-testid="skip-intro-movies"]').setValue(true)
    await wrapper.get('.primary-button').trigger('click')

    expect(wrapper.emitted('save')[0][0]).toMatchObject({
      ai_enabled: true,
      ai_model: 'example-model',
      check_outdated_mods: true,
      live_mod_detection: false,
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

  it('keeps hidden MODs hidden by default and saves the visibility preference', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: { language: 'zh-CN' },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    const visibility = wrapper.get('[data-testid="show-hidden-mods"]')
    expect(visibility.element.checked).toBe(false)
    await visibility.setValue(true)
    await wrapper.get('.primary-button').trigger('click')

    expect(wrapper.emitted('save')[0][0].show_hidden_mods).toBe(true)
  })

  it('shows editable keyboard shortcuts and saves their enabled preference', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: {
          language: 'zh-CN',
          keyboard_shortcuts_enabled: true,
        },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    await wrapper.get('[data-testid="settings-tab-shortcuts"]').trigger('click')

    expect(wrapper.get('[data-testid="settings-page-shortcuts"]').isVisible()).toBe(true)
    expect(wrapper.get('[data-testid="shortcut-open-workshop"]').text()).toContain('Shift + W')
    expect(wrapper.get('[data-testid="shortcut-open-rpfm"]').text()).toContain('Shift + R')
    expect(wrapper.get('[data-testid="shortcut-toggle-active"]').text()).toContain('Shift + E')
    expect(wrapper.get('[data-testid="shortcut-launch-game"]').text()).toContain('Shift + Enter')

    const workshopBinding = wrapper.get('[data-testid="shortcut-input-open-workshop"]')
    await workshopBinding.trigger('click')
    await workshopBinding.trigger('keydown', { key: 'k', ctrlKey: true, altKey: true })
    expect(workshopBinding.text()).toContain('Ctrl + Alt + K')

    const rpfmBinding = wrapper.get('[data-testid="shortcut-input-open-rpfm"]')
    await rpfmBinding.trigger('click')
    await rpfmBinding.trigger('keydown', { key: 'k', ctrlKey: true, altKey: true })
    expect(wrapper.get('[data-testid="shortcut-error"]').text()).toContain('该快捷键已被其他功能使用')
    expect(rpfmBinding.text()).toContain('请按下新的快捷键')
    await rpfmBinding.trigger('keydown', { key: 'Escape' })
    expect(rpfmBinding.text()).toContain('Shift + R')

    await wrapper.get('[data-testid="keyboard-shortcuts-enabled"]').setValue(false)
    await wrapper.get('.modal-footer .primary-button').trigger('click')

    expect(wrapper.emitted('save').at(-1)[0]).toMatchObject({
      keyboard_shortcuts_enabled: false,
      keyboard_shortcuts: expect.objectContaining({ 'open-workshop': 'Ctrl+Alt+K' }),
    })
  })

  it('switches to Three Kingdoms, keeps per-game paths, and requests detection for that game', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: {
          language: 'zh-CN',
          selected_game: 'warhammer3',
          game_installations: {
            warhammer3: {
              game_path: 'D:/Steam/steamapps/common/Total War WARHAMMER III',
              workshop_path: 'D:/Steam/steamapps/workshop/content/1142710',
            },
            three_kingdoms: { game_path: '', workshop_path: '' },
          },
        },
        health: { game_ready: false },
      },
      global: { plugins: [createPinia()] },
    })

    const game = wrapper.get('[data-testid="game-select"]')
    await game.get('.themed-select-trigger').trigger('click')
    await game.get('[data-value="three_kingdoms"]').trigger('click')

    expect(wrapper.get('[data-testid="game-path-input"]').attributes('placeholder')).toContain('Total War THREE KINGDOMS')
    expect(wrapper.get('[data-testid="workshop-path-input"]').attributes('placeholder')).toContain('779340')
    expect(wrapper.get('[data-testid="three-kingdoms-manual-path"]').exists()).toBe(true)
    expect(wrapper.emitted('detect').at(-1)).toEqual(['three_kingdoms'])

    await wrapper.get('[data-testid="game-path-input"]').setValue('D:/Steam/steamapps/common/Total War THREE KINGDOMS')
    await wrapper.get('.modal-footer .primary-button').trigger('click')
    expect(wrapper.emitted('save').at(-1)[0]).toMatchObject({
      selected_game: 'three_kingdoms',
      game_installations: {
        warhammer3: {
          game_path: 'D:/Steam/steamapps/common/Total War WARHAMMER III',
        },
        three_kingdoms: {
          game_path: 'D:/Steam/steamapps/common/Total War THREE KINGDOMS',
        },
      },
    })
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

  it('exposes automatic checks and changelog actions without a custom channel', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: {
          language: 'zh-CN',
          check_updates_automatically: true,
        },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    await wrapper.get('[data-testid="auto-update-check"]').setValue(false)
    await wrapper.get('.update-check-button').trigger('click')
    expect(wrapper.emitted('check-update')[0]).toEqual([])
    expect(wrapper.find('[data-testid="update-manifest-url"]').exists()).toBe(false)

    const changelogButton = wrapper.findAll('button').find(button => button.text() === '更新日志')
    await changelogButton.trigger('click')
    expect(wrapper.emitted('show-changelog')).toHaveLength(1)

    await wrapper.get('.modal-footer .primary-button').trigger('click')
    expect(wrapper.emitted('save')[0][0]).toMatchObject({
      check_updates_automatically: false,
    })
    expect(wrapper.emitted('save')[0][0]).not.toHaveProperty('update_manifest_url')
  })

  it('checks the built-in repositories without exposing a custom channel field', async () => {
    const wrapper = mount(SettingsModal, {
      props: {
        open: true,
        settings: {
          language: 'zh-CN',
          check_updates_automatically: true,
        },
        health: {},
      },
      global: { plugins: [createPinia()] },
    })

    const button = wrapper.get('.update-check-button')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')

    expect(wrapper.emitted('check-update')[0]).toEqual([])
    expect(wrapper.find('[data-testid="update-manifest-url"]').exists()).toBe(false)
  })

  it('splits settings into five pages and exposes the project support page', async () => {
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
      expect.stringContaining('快捷键'),
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
