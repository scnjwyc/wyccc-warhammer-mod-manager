// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('../bridge', () => ({ invoke: invokeMock }))

import { gameDataSettingsSignature, useAppStore } from '../store'

describe('game data settings state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    invokeMock.mockReset()
  })

  it('automatically generates a patch when changed settings are saved', async () => {
    const settings = {
      language: 'zh-CN',
      unit_model_multiplier: 2,
      disable_unit_friendly_fire: true,
      disable_spell_friendly_fire: false,
    }
    invokeMock.mockResolvedValue({ settings, patch: { path: 'game-data.pack' } })
    const store = useAppStore()
    store.settings = { language: 'zh-CN', unit_model_multiplier: 1 }
    store.mods = [{ id: 'example', pack_name: 'example.pack' }]
    store.activeIds = ['example']

    await store.saveGameDataSettings({
      unit_model_multiplier: 2,
      disable_unit_friendly_fire: true,
      disable_spell_friendly_fire: false,
    })

    expect(invokeMock).toHaveBeenCalledWith(
      'generate_game_data_patch',
      {
        unit_model_multiplier: 2,
        disable_unit_friendly_fire: true,
        disable_spell_friendly_fire: false,
      },
      ['example'],
    )
    expect(store.settings).toEqual(settings)
    expect(store.mods).toEqual([{ id: 'example', pack_name: 'example.pack' }])
    expect(store.activeIds).toEqual(['example'])
  })

  it('does not regenerate a changed draft already generated in this window session', async () => {
    const changes = {
      unit_model_multiplier: 2,
      disable_unit_friendly_fire: true,
      disable_spell_friendly_fire: false,
    }
    invokeMock.mockResolvedValue({ settings: changes })
    const store = useAppStore()
    store.settings = {
      unit_model_multiplier: 1,
      disable_unit_friendly_fire: false,
      disable_spell_friendly_fire: false,
    }

    await store.saveGameDataSettings(changes, gameDataSettingsSignature(changes))

    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(invokeMock).toHaveBeenCalledWith('save_game_data_settings', changes)
  })

  it('blocks game launch for the full patch-generation operation', async () => {
    const changes = {
      unit_model_multiplier: 2,
      disable_unit_friendly_fire: false,
      disable_spell_friendly_fire: false,
    }
    let completeGeneration
    invokeMock.mockImplementation(method => {
      if (method !== 'generate_game_data_patch') {
        throw new Error(`unexpected RPC: ${method}`)
      }
      return new Promise(resolve => { completeGeneration = resolve })
    })
    const store = useAppStore()
    store.activeIds = ['example']

    const generation = store.generateGameDataPatch(changes)
    await vi.waitFor(() => expect(store.busy).toContain('补丁'))

    await expect(store.launch()).rejects.toThrow('补丁')
    expect(invokeMock.mock.calls.some(([method]) => method === 'launch_game')).toBe(false)

    completeGeneration({ settings: changes, patch: { path: 'game-data.pack' } })
    await generation
    expect(store.busy).toBe('')
  })

  it('uses Workshop subscription status independently of scanned or active mods', async () => {
    const store = useAppStore()
    store.mods = [
      { id: 'unit-size', pack_name: 'wyccc_dynamic_unit_size.pack' },
      { id: 'friendly-fire', pack_name: 'WYCCC_DYNAMIC_NO_FRIENDLY_FIRE.PACK' },
    ]
    store.activeIds = ['friendly-fire']
    invokeMock.mockResolvedValue({
      items: {
        unit_size: {
          workshop_id: '3765783838',
          title: 'Dynamic Unit Size',
          pack_name: 'wyccc_dynamic_unit_size.pack',
          subscribed: true,
        },
        friendly_fire: {
          workshop_id: '3765783977',
          title: 'Dynamic No Friendly Fire',
          pack_name: 'wyccc_dynamic_no_friendly_fire.pack',
          subscribed: false,
        },
      },
      warning: '',
    })

    expect(typeof store.refreshGameDataFeatures).toBe('function')
    await store.refreshGameDataFeatures()

    expect(store.gameDataFeatureSubscribed('unit_size')).toBe(true)
    expect(store.gameDataFeatureSubscribed('friendly_fire')).toBe(false)
    expect(store.gameDataFeatures.unit_size.title).toBe('Dynamic Unit Size')
    expect(store.mods).toHaveLength(2)
    expect(store.activeIds).toEqual(['friendly-fire'])
    expect(invokeMock).toHaveBeenCalledWith('get_game_data_feature_status')
  })
})
