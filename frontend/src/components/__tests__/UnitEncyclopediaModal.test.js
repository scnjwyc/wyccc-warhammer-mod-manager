import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyInterfaceLanguage } from '../../languages'

vi.mock('../../bridge', () => ({ invoke: vi.fn() }))
import { invoke } from '../../bridge'
import UnitEncyclopediaModal from '../UnitEncyclopediaModal.vue'
import App from '../../App.vue'
import { useAppStore } from '../../store'

const unit = (key, name, overrides = {}) => ({
  key, name, races: ['empire'], caste: 'melee_infantry', group: 'infantry', category: '持剑步兵',
  group_name: '', description: '坚守阵线。', model_count: 120, armour_value: 30, health: 8280,
  morale: 60, speed: 30, melee_attack: 32, melee_defence: 32, weapon_strength: 28, charge_bonus: 14,
  recruitment_cost: 375, upkeep_cost: 100, melee_damage: 21, melee_ap_damage: 7, range: 0,
  features: [{ key: 'hide', name: '于森林中隐蔽', description: '森林隐蔽', icon: '' }],
  source_chain: ['原版', 'Test MOD'], icon: 'ui/card.png', portrait: 'ui/portrait.png', ...overrides,
})
const data = () => ({
  token: 'session', source_count: 2, source_pack_names: ['db.pack', 'test.pack'], art: {}, asset_warnings: [],
  races: [{ key: 'empire', name: '帝国', count: 2, image: 'ui/race.png', crest: '' },
    { key: 'cathay', name: '震旦', count: 1, image: '', crest: '' }],
  units: [unit('sword', '剑士'), unit('bow', '弓箭手', { range: 160, ammo: 24, missile_strength: 22,
    missile_damage: 18, missile_ap_damage: 4, firing_interval: 9.5, projectile_count: 6 }), unit('jade', '玉勇', { races: ['cathay'] })],
})
let wrapper
let host
const open = async () => {
  wrapper = mount(UnitEncyclopediaModal, { props: { open: true } })
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  applyInterfaceLanguage('zh-CN')
  invoke.mockImplementation(async method => method === 'get_unit_encyclopedia' ? data() : {})
})
afterEach(() => { wrapper?.unmount(); host?.remove() })

describe('unit encyclopedia', () => {
  it('opens with factions, selects a unit, shows live stats and returns to factions', async () => {
    await open()
    expect(wrapper.findAll('[data-race]')).toHaveLength(2)
    expect(wrapper.findAll('[data-unit]')).toHaveLength(0)
    await wrapper.get('[data-race="empire"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-unit]')).toHaveLength(2)
    expect(wrapper.get('.encyclopedia-detail h3').text()).toBe('剑士')
    expect(wrapper.get('.encyclopedia-health').text()).toContain('8,280')
    expect(wrapper.get('[data-stat="melee_attack"] dd').text()).toBe('32')
    await wrapper.get('[data-unit="bow"]').trigger('click')
    expect(wrapper.get('[data-stat="range"] dd').text()).toBe('160')
    expect(wrapper.get('[data-testid="firing-interval"]').text()).toContain('9.5 秒')
    expect(wrapper.get('[data-testid="projectile-count"]').text()).toContain('6')
    expect(wrapper.get('[data-unit="bow"]').attributes('aria-pressed')).toBe('true')
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.findAll('[data-race]')).toHaveLength(2)
    expect(wrapper.emitted('close')).toBeUndefined()
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('searches factions and units by name or key and keeps factions isolated', async () => {
    await open()
    await wrapper.get('input[type="search"]').setValue('震旦')
    expect(wrapper.findAll('[data-race]')).toHaveLength(1)
    await wrapper.get('[data-race="cathay"]').trigger('click')
    expect(wrapper.findAll('[data-unit]')).toHaveLength(1)
    expect(wrapper.get('[data-unit]').attributes('data-unit')).toBe('jade')
    await wrapper.get('input[type="search"]').setValue('sword')
    expect(wrapper.findAll('[data-unit]')).toHaveLength(0)
    expect(wrapper.text()).toContain('没有符合条件的内容')
    await wrapper.get('input[type="search"]').setValue('jade')
    expect(wrapper.findAll('[data-unit]')).toHaveLength(1)
  })

  it('shows all units in exactly two roster tabs without numbered pagination', async () => {
    const result = data()
    result.units = [...Array.from({ length: 190 }, (_, i) => unit(`unit_${i}`, `单位 ${i}`)),
      unit('lord', '领主', { caste: 'lord', group: 'lord' }), unit('hero', '英雄', { caste: 'hero', group: 'hero' })]
    invoke.mockImplementation(async method => method === 'get_unit_encyclopedia' ? result : {})
    await open()
    await wrapper.get('[data-race="empire"]').trigger('click')
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-unit]')).toHaveLength(2)
    expect(wrapper.get('.encyclopedia-detail h3').text()).toBe('领主')
    await wrapper.get('[data-roster="units"]').trigger('click')
    expect(wrapper.findAll('[data-unit]')).toHaveLength(190)
    expect(wrapper.find('.encyclopedia-pagination').exists()).toBe(false)
    await wrapper.get('input[type="search"]').setValue('unit_189')
    expect(wrapper.findAll('[data-unit]')).toHaveLength(1)
    await wrapper.get('input[type="search"]').setValue('英雄')
    expect(wrapper.get('[data-unit]').attributes('data-unit')).toBe('hero')
    expect(wrapper.get('[data-roster="characters"]').attributes('aria-selected')).toBe('true')
  })

  it('uses the returned snapshot token for images and survives missing art', async () => {
    await open()
    expect(invoke).toHaveBeenCalledWith('get_unit_encyclopedia_images', 'session', ['ui/race.png'])
    await wrapper.get('[data-race="empire"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.encyclopedia-card-fallback')).toHaveLength(2)
    expect(wrapper.find('img[src=""]').exists()).toBe(false)
    expect(invoke.mock.calls.every(([method]) => !method.startsWith('save'))).toBe(true)
  })

  it('ignores a late response after closing and reloading', async () => {
    let resolveFirst
    invoke.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
    wrapper = mount(UnitEncyclopediaModal, { props: { open: true } })
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    await flushPromises()
    resolveFirst({ ...data(), races: [{ key: 'old', name: '过期派系' }] })
    await flushPromises()
    expect(wrapper.find('[data-race="empire"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('过期派系')
    expect(invoke.mock.calls.filter(([method]) => method === 'get_unit_encyclopedia')).toHaveLength(2)
  })

  it('reports a read failure and lets the user retry', async () => {
    invoke.mockRejectedValueOnce(new Error('Pack has changed'))
    await open()
    expect(wrapper.get('[role="alert"]').text()).toContain('Pack has changed')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-race]')).toHaveLength(2)
  })

  it('renders no-match state when the current list has no units', async () => {
    invoke.mockResolvedValueOnce({ ...data(), races: [], units: [] })
    await open()
    expect(wrapper.text()).toContain('没有符合条件的内容')
    expect(wrapper.findAll('[data-unit]')).toHaveLength(0)
  })

  const openAppCatalogue = async (subscribed = true) => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3', language: 'zh-CN' }
    store.pathHealth = { game_ready: true }
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    vi.spyOn(store, 'refreshRuntime').mockResolvedValue({})
    let edits = {}
    invoke.mockImplementation(async (method, payload, selectedKey) => {
      const catalogue = data()
      catalogue.units.push(unit('sword_mounted', '剑士（坐骑）'))
      catalogue.units = catalogue.units.map(u => ({ ...u, ...edits[u.key] }))
      if (method === 'get_unit_encyclopedia') return catalogue
      if (method === 'get_unit_data_feature_status') return { required: true, subscribed }
      if (method === 'get_mod_diagnostics_history') return []
      if (method === 'get_unit_data_list') return {
        units: catalogue.units.filter(u => !selectedKey || u.key === selectedKey).map(u => ({ ...u, enabled: true, edited: edits[u.key] || {} })), stats: {},
        partial: Boolean(selectedKey), saved_edits: edits,
      }
      if (method === 'save_unit_data_edits') edits = payload
      return {}
    })
    host = document.createElement('div')
    document.body.appendChild(host)
    wrapper = shallowMount(App, { attachTo: host, global: { plugins: [pinia], stubs: {
      UnitEncyclopediaModal: false, UnitDataModificationModal: false, ConfirmationModal: false, teleport: true,
    } } })
    await flushPromises()
    await wrapper.get('[data-testid="unit-encyclopedia-button"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-race="empire"]').trigger('click')
    await wrapper.get('[data-unit="sword"]').trigger('click')
    return store
  }

  it('opens exactly the selected unit in the real editor, then resumes and refreshes the same roster', async () => {
    const store = await openAppCatalogue()
    await wrapper.get('.encyclopedia-toolbar input').setValue('sword')
    store.runtime.running = true
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="encyclopedia-edit-unit"]').attributes('disabled')).toBeDefined()
    store.runtime.running = false
    await wrapper.vm.$nextTick()
    await wrapper.get('[data-testid="encyclopedia-edit-unit"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.encyclopedia-backdrop').isVisible()).toBe(false)
    expect(wrapper.get('[data-testid="unit-data-search"]').element.value).toBe('sword')
    expect(wrapper.findAll('.unit-data-row')).toHaveLength(1)
    expect(wrapper.get('.unit-data-keytag').text()).toBe('sword')
    expect(invoke).toHaveBeenCalledWith('get_unit_data_list', 'session', 'sword')
    await wrapper.get('[data-testid="unit-data-search"]').setValue('')
    await flushPromises()
    expect(wrapper.findAll('.unit-data-row')).toHaveLength(4)
    await wrapper.get('.unit-data-modal .icon-button').trigger('click')
    expect(wrapper.get('.encyclopedia-backdrop').isVisible()).toBe(true)
    expect(wrapper.get('[data-unit="sword"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('.encyclopedia-toolbar input').element.value).toBe('sword')
    expect(invoke.mock.calls.filter(([method]) => method === 'get_unit_encyclopedia')).toHaveLength(1)
    await wrapper.get('[data-testid="encyclopedia-edit-unit"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="unit-melee_attack-sword"]').setValue('41')
    await wrapper.get('[data-testid="unit-data-save"]').trigger('click')
    await flushPromises()
    expect(invoke).toHaveBeenCalledWith('save_unit_data_edits', { sword: { melee_attack: 41 } })
    expect(wrapper.find('.unit-data-modal').exists()).toBe(false)
    expect(wrapper.get('[data-unit="sword"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-stat="melee_attack"] dd').text()).toBe('41')
    expect(wrapper.get('.encyclopedia-toolbar input').element.value).toBe('sword')
  })

  it('keeps the existing subscription requirement visible and returns to the selected unit', async () => {
    await openAppCatalogue(false)
    await wrapper.get('[data-testid="encyclopedia-edit-unit"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.unit-data-modal').exists()).toBe(false)
    expect(wrapper.get('[role="alertdialog"]').isVisible()).toBe(true)
    expect(wrapper.get('.encyclopedia-backdrop').isVisible()).toBe(false)
    await wrapper.get('[data-testid="confirmation-confirm"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.encyclopedia-backdrop').isVisible()).toBe(true)
    expect(wrapper.get('[data-unit="sword"]').attributes('aria-pressed')).toBe('true')
    expect(invoke.mock.calls.some(([method]) => method === 'get_unit_data_list')).toBe(false)
  })
})
