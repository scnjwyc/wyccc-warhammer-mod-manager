// @vitest-environment jsdom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import App from '../App.vue'
import ModList from '../components/ModList.vue'
import { applyInterfaceLanguage } from '../languages'
import { useAppStore } from '../store'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))

it('creates an SFO patch from the selected mod and keeps it disabled', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  applyInterfaceLanguage('zh-CN')
  const store = useAppStore()
  const mod = { id: 'a', pack_name: 'a.pack', path: 'G:/a.pack', source: 'workshop' }
  const patch = { id: 'p', pack_name: '!a_sfo.pack', path: 'G:/data/!a_sfo.pack', alias: 'A SFO补丁' }
  store.settings = { selected_game: 'warhammer3', language: 'zh-CN' }
  store.pathHealth = { game_ready: true }
  store.mods = [mod]
  store.selectedId = mod.id
  store.selectedIds = [mod.id]
  store.activeIds = [mod.id]
  vi.spyOn(store, 'bootstrap').mockResolvedValue({})
  vi.spyOn(store, 'refreshRuntime').mockResolvedValue({})
  invokeMock.mockImplementation(async method => method === 'create_sfo_patch' ? {
    mod_id: patch.id, path: patch.path, alias: patch.alias,
    units: [{ unit: 'archers', issues: [], stats: { hp: [100, 160] } }],
    skills: [{ key: 'fire_spell', missing: [],
      damage: [{ key: 'burn', table: 'special_ability_phases', stats: { damage_amount: [20, 26] } }],
    }],
    scan: { game_id: 'warhammer3', mods: [mod, patch], enabled_order: [mod.id] },
  } : {})

  const wrapper = shallowMount(App, {
    global: { plugins: [pinia], stubs: { ModContextMenu: false, SfoPatchModal: false } },
  })
  try {
    await flushPromises()
    wrapper.findAllComponents(ModList)[0].vm.$emit('context-menu', { mod, x: 20, y: 20 })
    await wrapper.vm.$nextTick()
    await wrapper.get('[data-testid="context-create-sfo-patch"]').trigger('click')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('create_sfo_patch', mod.id)
    expect(store.activeIds).toEqual([mod.id])
    expect(store.selectedId).toBe(patch.id)
    const dialog = wrapper.get('[data-testid="sfo-patch-modal"]')
    expect(dialog.text()).toContain(patch.alias)
    expect(dialog.text()).toContain('100 → 160')
    expect(dialog.text()).toContain('技能伤害 ×1.30')
    expect(dialog.text()).toContain('20 → 26')
  } finally {
    wrapper.unmount()
  }
})
