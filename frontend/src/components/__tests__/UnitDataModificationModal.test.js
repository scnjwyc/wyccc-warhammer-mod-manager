import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../bridge', () => ({ invoke: vi.fn() }))

import { invoke } from '../../bridge'
import UnitDataModificationModal from '../UnitDataModificationModal.vue'

const sampleUnits = [
  {
    key: 'inf_swordsmen',
    mod_name: 'SFO',
    source_chain: ['原版', 'SFO'],
    name: 'Swordsmen',
    race: '帝国',
    caste: 'melee_infantry',
    enabled: true,
    campaign_cap: 4,
    recruitment_cost: 400,
    upkeep_cost: 100,
    model_count: 90,
    model_count_locked: false,
    morale: 55,
    armour_value: 10,
    armour_options: [10, 20, 100],
    hit_points: 8,
    total_hp: 720,
    charge_bonus: 15,
    melee_attack: 28,
    melee_defence: 32,
    missile_block_chance: 0,
    movement_speed: 0,
    melee_attack_speed: 0,
    ammo: 0,
    missile_resistance: 0,
    fire_resistance: 0,
    magic_resistance: 0,
    physical_resistance: 0,
    ward_save: 0,
    melee_damage: 25,
    melee_ap_damage: 8,
    melee_bonus_v_cavalry: 0,
    melee_bonus_v_infantry: 0,
    missile_damage: 0,
    missile_ap_damage: 0,
    missile_bonus_v_cavalry: 0,
    missile_bonus_v_infantry: 0,
    range: 0,
    reload: 10,
    ranged_attack_speed: 0,
    accuracy: 40,
    edited: {},
  },
  {
    key: 'veh_chariot',
    mod_name: 'SFO',
    source_chain: ['原版', 'SFO'],
    name: 'Chariot',
    race: '帝国',
    caste: 'chariot',
    enabled: true,
    campaign_cap: 2,
    recruitment_cost: 900,
    upkeep_cost: 250,
    model_count: 12,
    model_count_locked: false,
    morale: 50,
    armour_value: 60,
    armour_options: [60, 80],
    hit_points: 5,
    total_hp: 60,
    charge_bonus: 40,
    melee_attack: 20,
    melee_defence: 25,
    missile_block_chance: 0,
    movement_speed: 0,
    melee_attack_speed: 0,
    ammo: 0,
    missile_resistance: 0,
    fire_resistance: 0,
    magic_resistance: 0,
    physical_resistance: 0,
    ward_save: 0,
    melee_damage: 25,
    melee_ap_damage: 8,
    melee_bonus_v_cavalry: 0,
    melee_bonus_v_infantry: 0,
    missile_damage: 0,
    missile_ap_damage: 0,
    missile_bonus_v_cavalry: 0,
    missile_bonus_v_infantry: 0,
    range: 0,
    reload: 10,
    ranged_attack_speed: 0,
    accuracy: 30,
    edited: {},
  },
]

describe('unit data modification modal', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(invoke).mockResolvedValue({
      units: sampleUnits,
      stats: { unit_count: 2, edited_unit_count: 0 },
    })
  })

  it('loads and renders the stacked unit table', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await wrapper.vm.$nextTick()
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(invoke).toHaveBeenCalledWith('get_unit_data_list')
    expect(wrapper.findAll('.unit-data-row')).toHaveLength(2)
    expect(wrapper.get('[data-testid="unit-data-count"]').text()).toContain('2')
  })

  it('keeps the configured column widths fixed in the rendered table', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="unit-data-header-mod_name"]').attributes('style')).toContain('width: 351px')
    expect(wrapper.get('[data-testid="unit-data-header-mod_name"]').attributes('style')).toContain('min-width: 351px')
    expect(wrapper.get('[data-testid="unit-data-header-name"]').attributes('style')).toContain('width: 231.66px')
    expect(wrapper.get('[data-testid="unit-data-header-race"]').attributes('style')).toContain('width: 126px')
    expect(wrapper.get('[data-testid="unit-data-header-campaign_cap"]').attributes('style')).toContain('width: 105px')
    expect(wrapper.get('[data-testid="unit-data-header-melee_damage"]').attributes('style')).toContain('width: 126.36px')
    expect(wrapper.find('col[style="width: 147.42px;"]').exists()).toBe(true)
  })

  it('places missile resistance immediately before fire resistance', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const headers = wrapper.findAll('th').map(header => header.attributes('data-testid'))
    expect(headers.indexOf('unit-data-header-missile_resistance'))
      .toBe(headers.indexOf('unit-data-header-fire_resistance') - 1)
  })

  it('shows movement speed after leadership for Warhammer', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false, gameId: 'warhammer3' } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const headers = wrapper.findAll('th').map(header => header.attributes('data-testid'))
    expect(headers).toContain('unit-data-header-movement_speed')
    expect(headers.indexOf('unit-data-header-movement_speed'))
      .toBe(headers.indexOf('unit-data-header-morale') + 1)
  })

  it('uses Three Kingdoms labels and fields without resistance or reload columns', async () => {
    const wrapper = mount(UnitDataModificationModal, {
      props: { open: false, gameId: 'three_kingdoms' },
    })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const headers = wrapper.findAll('th').map(header => header.attributes('data-testid'))
    expect(wrapper.get('[data-testid="unit-data-header-morale"]').text()).toContain('士气')
    expect(wrapper.get('[data-testid="unit-data-header-melee_defence"]').text()).toContain('近战闪避')
    expect(headers.indexOf('unit-data-header-morale'))
      .toBe(headers.indexOf('unit-data-header-movement_speed') - 1)
    expect(headers.indexOf('unit-data-header-movement_speed'))
      .toBe(headers.indexOf('unit-data-header-armour') - 1)
    expect(headers).toContain('unit-data-header-missile_block_chance')
    expect(headers).toContain('unit-data-header-movement_speed')
    expect(headers).toContain('unit-data-header-melee_attack_speed')
    expect(headers).toContain('unit-data-header-ranged_attack_speed')
    expect(headers).toContain('unit-data-header-melee_bonus_v_cavalry')
    expect(headers).toContain('unit-data-header-missile_bonus_v_infantry')
    expect(headers).not.toContain('unit-data-header-missile_resistance')
    expect(headers).not.toContain('unit-data-header-fire_resistance')
    expect(headers).not.toContain('unit-data-header-reload')
    expect(headers).not.toContain('unit-data-header-explosion_damage')
    expect(headers).not.toContain('unit-data-header-explosion_ap_damage')
    expect(headers).not.toContain('unit-data-header-race')
  })

  it('rounds Three Kingdoms movement speed to one decimal place', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [{ ...sampleUnits[0], movement_speed: 35.26 }],
      stats: { unit_count: 1, edited_unit_count: 0 },
    })
    const wrapper = mount(UnitDataModificationModal, {
      props: { open: false, gameId: 'three_kingdoms' },
    })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const input = wrapper.get('[data-testid="unit-movement_speed-inf_swordsmen"]')
    expect(input.element.value).toBe('35.3')
    expect(input.attributes('step')).toBe('0.1')
  })

  it('rounds Warhammer movement speed to one decimal place', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [{ ...sampleUnits[0], movement_speed: 35.26 }],
      stats: { unit_count: 1, edited_unit_count: 0 },
    })
    const wrapper = mount(UnitDataModificationModal, {
      props: { open: false, gameId: 'warhammer3' },
    })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const input = wrapper.get('[data-testid="unit-movement_speed-inf_swordsmen"]')
    expect(input.element.value).toBe('35.3')
    expect(input.attributes('step')).toBe('0.1')
  })

  it('rounds Three Kingdoms melee attack speed to one decimal place', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [{ ...sampleUnits[0], melee_attack_speed: 2.56 }],
      stats: { unit_count: 1, edited_unit_count: 0 },
    })
    const wrapper = mount(UnitDataModificationModal, {
      props: { open: false, gameId: 'three_kingdoms' },
    })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const input = wrapper.get('[data-testid="unit-melee_attack_speed-inf_swordsmen"]')
    expect(input.element.value).toBe('2.6')
    expect(input.attributes('step')).toBe('0.1')

    await input.setValue(25.06)
    await wrapper.get('[data-testid="unit-data-save"]').trigger('click')
    expect(wrapper.emitted('save')[0][0]).toEqual({
      inf_swordsmen: { melee_attack_speed: 25.1 },
    })
  })

  it('filters rows through the search bar', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    await wrapper.get('[data-testid="unit-data-search"]').setValue('chariot')
    expect(wrapper.findAll('.unit-data-row')).toHaveLength(1)
    expect(wrapper.text()).toContain('Chariot')
  })

  it('applies the MOD search passed by a list gear', async () => {
    const wrapper = mount(UnitDataModificationModal, {
      props: { open: false, initialSearch: 'SFO' },
    })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.unit-data-row')).toHaveLength(2)
    expect(wrapper.get('[data-testid="unit-data-search"]').element.value).toBe('SFO')
  })

  it('emits only edited fields when saving', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    await wrapper
      .get('[data-testid="unit-campaign_cap-inf_swordsmen"]')
      .setValue(9)
    await wrapper.get('[data-testid="unit-data-save"]').trigger('click')

    const payload = wrapper.emitted('save')[0][0]
    expect(payload).toEqual({ inf_swordsmen: { campaign_cap: 9 } })
  })

  it('allows the model count of a single-model unit to be edited', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [
        {
          ...sampleUnits[0],
          key: 'single_monster',
          model_count: 1,
          model_count_locked: false,
          original_values: { model_count: 1 },
        },
      ],
      stats: { unit_count: 1, edited_unit_count: 0 },
    })
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const input = wrapper.get('[data-testid="unit-model_count-single_monster"]')
    expect(input.attributes('disabled')).toBeUndefined()
    await input.setValue(3)
    await wrapper.get('[data-testid="unit-data-save"]').trigger('click')

    expect(wrapper.emitted('save')[0][0]).toEqual({ single_monster: { model_count: 3 } })
  })

  it('disables only the fields the Three Kingdoms backend marks as unsafe', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [
        {
          ...sampleUnits[0],
          key: 'three_kingdoms_artillery',
          model_count_locked: true,
          hit_points_locked: true,
          enabled_locked: true,
        },
      ],
      stats: { unit_count: 1, edited_unit_count: 0 },
    })
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="unit-model_count-three_kingdoms_artillery"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="unit-hit_points-three_kingdoms_artillery"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="unit-enabled-three_kingdoms_artillery"]').attributes('disabled')).toBeDefined()
  })

  it('uses land_units HP as model HP and updates total live', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const hpInput = wrapper.get('[data-testid="unit-hit_points-inf_swordsmen"]')
    expect(hpInput.element.value).toBe('8') // land_units.bonus_hit_points
    await hpInput.setValue(70)
    const total = wrapper.get('[data-testid="unit-total-hp-inf_swordsmen"]')
    expect(Number(total.text())).toBe(70 * 90)
  })

  it('persists armour dropdown choices by value', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const select = wrapper.find('.unit-data-select')
    expect(select.element.value).toBe('10')
    await select.setValue('100')
    await wrapper.get('[data-testid="unit-data-save"]').trigger('click')

    const payload = wrapper.emitted('save')[0][0]
    expect(payload).toEqual({ inf_swordsmen: { armour: 100 } })
  })

  it('shows the key inside the name column on a left-aligned second line', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const cell = wrapper.findAll('.unit-data-row')[0].find('.unit-data-keytag')
    expect(cell.text()).toBe('inf_swordsmen')
  })

  it('translates the unit caste', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('近战步兵')
    expect(wrapper.text()).toContain('战车')
  })

  it('shows the source chain as a hover tooltip on the MOD name link', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    await wrapper.get('[data-testid="unit-source-chain-inf_swordsmen"]').trigger('mouseenter')
    const tooltip = wrapper.get('[data-testid="unit-data-tooltip"]')
    expect(tooltip.text()).toContain('原版')
    expect(tooltip.text()).toContain('SFO')
    await wrapper.get('[data-testid="unit-source-chain-inf_swordsmen"]').trigger('mouseleave')
    expect(wrapper.find('[data-testid="unit-data-tooltip"]').exists()).toBe(false)
  })

  it('shows field info as a hover tooltip on the header exclamation mark', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    await wrapper.get('[data-testid="unit-data-help-campaign_cap"]').trigger('mouseenter')
    const tooltip = wrapper.get('[data-testid="unit-data-tooltip"]')
    expect(tooltip.text()).toContain('main_units_tables')
  })

  it('sorts by a column when its header is clicked', async () => {
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    await wrapper.get('[data-testid="unit-data-header-campaign_cap"] .unit-data-th-label').trigger('click')
    const first = wrapper.findAll('.unit-data-row')[0]
    expect(first.find('.unit-data-keytag').text()).toContain('veh_chariot')
  })

  it('marks edited rows and shows the original value on hover', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [
        {
          ...sampleUnits[0],
          edited: { campaign_cap: 9 },
          original_values: { campaign_cap: 4 },
        },
        sampleUnits[1],
      ],
      stats: { unit_count: 2, edited_unit_count: 1 },
    })
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.get('.unit-data-name-edited').text()).toBe('Swordsmen')
    const removeUnitButton = wrapper.get('[data-testid="unit-remove-edits-inf_swordsmen"]')
    expect(removeUnitButton.exists()).toBe(true)
    expect(removeUnitButton.attributes('title')).toBeUndefined()
    expect(wrapper.get('[data-testid="unit-campaign_cap-inf_swordsmen"]').classes()).toContain('unit-data-edited-control')
    await wrapper.get('[data-testid="unit-campaign_cap-inf_swordsmen"]').trigger('mouseenter')
    expect(wrapper.get('[data-testid="unit-data-tooltip"]').text()).toContain('4')
  })

  it('removes one unit edit or all edits for its MOD with Shift', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [
        { ...sampleUnits[0], edited: { campaign_cap: 9 }, original_values: { campaign_cap: 4 } },
        { ...sampleUnits[1], edited: { campaign_cap: 7 }, original_values: { campaign_cap: 2 } },
      ],
      stats: { unit_count: 2, edited_unit_count: 2 },
    })
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    await wrapper.get('[data-testid="unit-remove-edits-inf_swordsmen"]').trigger('click')
    expect(wrapper.find('[data-testid="unit-remove-edits-inf_swordsmen"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="unit-remove-edits-veh_chariot"]').exists()).toBe(true)

    await wrapper.get('[data-testid="unit-remove-edits-veh_chariot"]').trigger('click', { shiftKey: true })
    expect(wrapper.findAll('.unit-data-remove')).toHaveLength(0)
    await wrapper.get('[data-testid="unit-data-save"]').trigger('click')
    expect(wrapper.emitted('save')[0][0]).toEqual({})
  })

  it('clears all unit edits from the lower-left button', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [
        { ...sampleUnits[0], edited: { campaign_cap: 9 }, original_values: { campaign_cap: 4 } },
        { ...sampleUnits[1], edited: { campaign_cap: 7 }, original_values: { campaign_cap: 2 } },
      ],
      stats: { unit_count: 2, edited_unit_count: 2 },
    })
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    await wrapper.get('[data-testid="unit-data-clear-all"]').trigger('click')
    expect(wrapper.findAll('.unit-data-remove')).toHaveLength(0)
    expect(wrapper.get('[data-testid="unit-data-clear-all"]').attributes('disabled')).toBeDefined()
  })

  it('removes an individual field edit with its right-aligned x button', async () => {
    vi.mocked(invoke).mockResolvedValue({
      units: [
        {
          ...sampleUnits[0],
          edited: { campaign_cap: 9, melee_damage: 40 },
          original_values: { campaign_cap: 4, melee_damage: 25 },
        },
        sampleUnits[1],
      ],
      stats: { unit_count: 2, edited_unit_count: 1 },
    })
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="unit-field-remove-campaign_cap-inf_swordsmen"]').exists()).toBe(true)
    await wrapper.get('[data-testid="unit-field-remove-campaign_cap-inf_swordsmen"]').trigger('click')
    expect(wrapper.find('[data-testid="unit-field-remove-campaign_cap-inf_swordsmen"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="unit-campaign_cap-inf_swordsmen"]').classes()).not.toContain('unit-data-edited-control')
    expect(wrapper.get('[data-testid="unit-field-remove-melee_damage-inf_swordsmen"]').exists()).toBe(true)

    await wrapper.get('[data-testid="unit-data-save"]').trigger('click')
    expect(wrapper.emitted('save')[0][0]).toEqual({ inf_swordsmen: { melee_damage: 40 } })
  })

  it('paginates with 200 rows per page', async () => {
    const many = Array.from({ length: 2050 }, (_, index) => ({
      ...sampleUnits[0],
      key: `unit_${index}`,
      name: `Unit ${index}`,
      campaign_cap: index,
      source_chain: ['原版'],
      edited: {},
    }))
    vi.mocked(invoke).mockResolvedValue({
      units: many,
      stats: { unit_count: 2050, edited_unit_count: 0 },
    })
    const wrapper = mount(UnitDataModificationModal, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.unit-data-row')).toHaveLength(200)
    expect(wrapper.get('[data-testid="unit-data-page-info"]').text()).toContain('11')
    await wrapper.get('[data-testid="unit-data-next"]').trigger('click')
    expect(wrapper.findAll('.unit-data-row')).toHaveLength(200)
    for (let index = 0; index < 9; index += 1) {
      await wrapper.get('[data-testid="unit-data-next"]').trigger('click')
    }
    expect(wrapper.findAll('.unit-data-row')).toHaveLength(50)
  })
})
