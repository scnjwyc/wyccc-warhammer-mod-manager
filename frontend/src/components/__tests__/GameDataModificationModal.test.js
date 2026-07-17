import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import GameDataModificationModal from '../GameDataModificationModal.vue'
import { applyInterfaceLanguage } from '../../languages'

const componentSource = readFileSync(
  resolve(process.cwd(), 'src/components/GameDataModificationModal.vue'),
  'utf8',
)

afterEach(() => applyInterfaceLanguage('zh-CN'))

describe('game data modification modal', () => {
  it('explains in every language that a 1× multiplier disables unit scaling', () => {
    const expected = {
      'zh-CN': ['1 倍', '关闭'],
      'en-US': ['1×', 'disables'],
      'ko-KR': ['1배', '꺼집니다'],
      'ru-RU': ['1×', 'отключает'],
      'ja-JP': ['1倍', '無効'],
    }

    for (const [language, terms] of Object.entries(expected)) {
      applyInterfaceLanguage(language)
      const wrapper = mount(GameDataModificationModal, {
        props: {
          open: true,
          settings: { unit_model_multiplier: 1 },
        },
      })
      const help = wrapper.get('.game-data-card-copy small').text()
      for (const term of terms) expect(help).toContain(term)
      wrapper.unmount()
    }
  })

  it('uses a 1-5 integer slider and emits all four game data settings', async () => {
    const wrapper = mount(GameDataModificationModal, {
      props: {
        open: true,
        settings: {
          unit_model_multiplier: 2,
          scale_lord_hero_health: false,
          disable_unit_friendly_fire: false,
          disable_spell_friendly_fire: true,
        },
      },
    })

    const multiplier = wrapper.get('[data-testid="unit-model-multiplier"]')
    expect(multiplier.attributes('type')).toBe('range')
    expect(multiplier.element.value).toBe('2')
    expect(multiplier.attributes('min')).toBe('1')
    expect(multiplier.attributes('max')).toBe('5')
    expect(multiplier.attributes('step')).toBe('1')
    expect(wrapper.get('[data-testid="unit-scale-value"]').text()).toContain('2')
    expect(wrapper.get('[data-testid="unit-scale-ticks"]').text()).toContain('1')
    expect(wrapper.get('[data-testid="unit-scale-ticks"]').text()).toContain('5')
    expect(wrapper.get('[data-testid="scale-lord-hero-health"]').element.checked).toBe(false)

    await multiplier.setValue('4')
    await wrapper.get('[data-testid="scale-lord-hero-health"]').setValue(true)
    await wrapper.get('[data-testid="disable-unit-friendly-fire"]').setValue(true)
    await wrapper.get('[data-testid="disable-spell-friendly-fire"]').setValue(false)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('save')[0][0]).toEqual({
      unit_model_multiplier: 4,
      scale_lord_hero_health: true,
      disable_unit_friendly_fire: true,
      disable_spell_friendly_fire: false,
    })
    expect(wrapper.text()).toContain('不会修改原始 Pack')
    expect(wrapper.text()).toContain('增益、治疗和友军光环')
  })

  it('spaces five tick labels across four equal slider intervals', () => {
    const tickRule = componentSource.match(/\.unit-scale-ticks\s*\{([^}]*)\}/)?.[1] ?? ''

    expect(tickRule).toContain('display: flex')
    expect(tickRule).toContain('justify-content: space-between')
    expect(tickRule).not.toContain('grid-template-columns')
  })

  it('normalizes legacy decimal multipliers to the nearest supported integer', async () => {
    const wrapper = mount(GameDataModificationModal, {
      props: {
        open: true,
        settings: { unit_model_multiplier: 2.5 },
      },
    })

    const multiplier = wrapper.get('[data-testid="unit-model-multiplier"]')
    expect(multiplier.element.value).toBe('3')

    await multiplier.setValue('5')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')[0][0].unit_model_multiplier).toBe(5)
  })

  it('has no manual patch generation control or event', async () => {
    const wrapper = mount(GameDataModificationModal, {
      props: {
        open: true,
        settings: {
          unit_model_multiplier: 2,
          scale_lord_hero_health: false,
          disable_unit_friendly_fire: false,
          disable_spell_friendly_fire: false,
        },
      },
    })

    expect(wrapper.find('[data-testid="generate-game-data-patch"]').exists()).toBe(false)
    expect(wrapper.vm.$options.emits).not.toContain('generate')
  })

  it('keeps all footer buttons in one right-side action row above the patch reminder', () => {
    const wrapper = mount(GameDataModificationModal, {
      props: {
        open: true,
      },
    })

    const footerContent = wrapper.get('[data-testid="game-data-footer-content"]')
    const actionRow = footerContent.get('[data-testid="game-data-footer-actions"]')
    const buttons = actionRow.findAll('button')
    expect(buttons).toHaveLength(2)
    expect(buttons[0].text()).toBe('取消')
    expect(buttons[1].attributes('type')).toBe('submit')

    const reminder = footerContent.get('[data-testid="game-data-regeneration-warning"]')
    expect(actionRow.element.nextElementSibling).toBe(reminder.element)
    expect(reminder.text()).toContain('启动游戏时')
    expect(reminder.text()).toContain('配置组或顺序')
    expect(reminder.text()).toContain('源 Pack')
    expect(reminder.text()).toContain('db.pack')
  })

  it('resets the draft from persisted settings whenever it reopens', async () => {
    const wrapper = mount(GameDataModificationModal, {
      props: {
        open: true,
        settings: { unit_model_multiplier: 3 },
      },
    })
    await wrapper.get('[data-testid="unit-model-multiplier"]').setValue('9')
    await wrapper.setProps({ open: false })
    await wrapper.setProps({
      open: true,
      settings: { unit_model_multiplier: 2.5, scale_lord_hero_health: true },
    })

    expect(wrapper.get('[data-testid="unit-model-multiplier"]').element.value).toBe('3')
    expect(wrapper.get('[data-testid="scale-lord-hero-health"]').element.checked).toBe(true)
  })

  it('disables unsubscribed features and names the Workshop MODs', () => {
    const wrapper = mount(GameDataModificationModal, {
      props: {
        open: true,
        settings: {
          unit_model_multiplier: 2,
          scale_lord_hero_health: true,
          disable_unit_friendly_fire: true,
          disable_spell_friendly_fire: true,
        },
        unitSizeSubscribed: false,
        friendlyFireSubscribed: false,
        unitSizeModName: 'Dynamic Unit Size',
        friendlyFireModName: 'Dynamic No Friendly Fire',
      },
    })

    expect(wrapper.get('[data-testid="unit-model-multiplier"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.get('[data-testid="scale-lord-hero-health"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.get('[data-testid="disable-unit-friendly-fire"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.get('[data-testid="disable-spell-friendly-fire"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.get('[data-testid="unit-size-requirement"]').text()).toContain('尚未订阅')
    expect(wrapper.get('[data-testid="unit-size-requirement"]').text()).toContain('Dynamic Unit Size')
    expect(wrapper.get('[data-testid="friendly-fire-requirement"]').text()).toContain('尚未订阅')
    expect(wrapper.get('[data-testid="friendly-fire-requirement"]').text()).toContain('Dynamic No Friendly Fire')
    expect(wrapper.text()).not.toContain('wyccc_dynamic_')
    expect(wrapper.get('button[type="submit"]').attributes()).toHaveProperty('disabled')
  })
})
