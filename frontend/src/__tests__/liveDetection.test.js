// @vitest-environment jsdom

import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('../bridge', () => ({ invoke: invokeMock }))

import { useAppStore } from '../store'
import App from '../App.vue'
import ModList from '../components/ModList.vue'

const emptyScan = revision => ({
  mods: [],
  enabled_order: [],
  missing_enabled_ids: [],
  warnings: [],
  mod_revision: revision,
})

describe('live MOD detection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    invokeMock.mockReset()
  })

  it('runs one quiet background scan when the filesystem revision advances', async () => {
    invokeMock.mockImplementation(async method => {
      if (method === 'get_runtime_status') return { running: false, mod_revision: 3 }
      if (method === 'scan_mods') return emptyScan(3)
      throw new Error(`Unexpected RPC: ${method}`)
    })
    const store = useAppStore()
    store.settings = { live_mod_detection: true }
    store.modRevision = 2

    await store.refreshRuntime()

    expect(invokeMock).toHaveBeenCalledWith('scan_mods', false)
    expect(store.modRevision).toBe(3)
    expect(store.liveModRefreshing).toBe(false)
  })

  it('refreshes Steam metadata when a newly subscribed Workshop MOD appears', async () => {
    const withoutMetadata = {
      ...emptyScan(3),
      mods: [{ id: 'steam:123:new.pack', source: 'workshop', workshop_id: '123', pack_name: 'new.pack' }],
    }
    const withMetadata = {
      ...withoutMetadata,
      mods: [{
        ...withoutMetadata.mods[0],
        display_name: 'Steam MOD name',
        author: 'Steam author',
      }],
    }
    invokeMock.mockImplementation(async (method, refreshWorkshop) => {
      if (method === 'get_runtime_status') return { running: false, mod_revision: 3 }
      if (method === 'scan_mods') return withoutMetadata
      if (method === 'refresh_workshop_metadata') return withMetadata
      throw new Error(`Unexpected RPC: ${method}`)
    })
    const store = useAppStore()
    store.settings = { live_mod_detection: true, fetch_workshop_metadata: true }
    store.modRevision = 2

    await store.refreshRuntime()
    await flushPromises()

    expect(invokeMock.mock.calls.filter(([method]) => method === 'scan_mods')).toEqual([
      ['scan_mods', false],
    ])
    expect(invokeMock).toHaveBeenCalledWith('refresh_workshop_metadata', ['123'], 'warhammer3')
    expect(store.mods[0].author).toBe('Steam author')
  })

  it('shows a newly downloaded MOD before its slow online metadata request finishes', async () => {
    const freshMod = { id: 'steam:123:new.pack', source: 'workshop', workshop_id: '123', pack_name: 'new.pack',
      effective_name: 'New downloaded MOD' }
    const localScan = { ...emptyScan(3), mods: [freshMod] }
    let finishMetadata
    invokeMock.mockImplementation(async (method, refreshWorkshop) => {
      if (method === 'get_runtime_status') return { running: false, mod_revision: 3 }
      if (method === 'scan_mods' && !refreshWorkshop) return localScan
      if (method === 'refresh_workshop_metadata') return new Promise(resolve => { finishMetadata = resolve })
      if (method === 'update_playset') return { playsets: [], current_playset: { id: 'test-playset' } }
      if (method === 'save_load_order') return { order_token: 'saved-order' }
      throw new Error(`Unexpected RPC: ${method}`)
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAppStore()
    store.settings = { live_mod_detection: true, fetch_workshop_metadata: true }
    store.modRevision = 2
    store.pathHealth = { game_ready: true }
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    const wrapper = shallowMount(App, { global: { plugins: [pinia], stubs: { ModList: false } } })
    const pending = store.refreshRuntime()
    try {
      await vi.waitFor(() => expect(finishMetadata).toBeTypeOf('function'))
      expect(store.mods.map(mod => mod.id)).toContain(freshMod.id)
      expect(store.busy).toBe('')
      expect(store.liveModRefreshing).toBe(false)
      const inactiveList = wrapper.findAllComponents(ModList).find(list => !list.props('active'))
      expect(inactiveList.text()).toContain('New downloaded MOD')
      await inactiveList.get('.enable-button').trigger('click')
      expect(store.activeIds).toContain(freshMod.id)
    } finally {
      finishMetadata({ ...localScan, mods: [{ ...freshMod, display_name: 'Steam MOD name' }] })
      await pending
      await flushPromises()
      wrapper.unmount()
    }
    expect(store.activeIds).toContain(freshMod.id)
  })

  it('does not scan while the game is running in low-consumption mode', async () => {
    invokeMock.mockResolvedValue({ running: true, mod_revision: 4 })
    const store = useAppStore()
    store.settings = { live_mod_detection: true }
    store.modRevision = 3

    await store.refreshRuntime()

    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(invokeMock).toHaveBeenCalledWith('get_runtime_status')
  })

  it('continues live scanning while the game is running when low-consumption mode is disabled', async () => {
    invokeMock.mockImplementation(async method => {
      if (method === 'get_runtime_status') return { running: true, mod_revision: 4 }
      if (method === 'scan_mods') return emptyScan(4)
      throw new Error(`Unexpected RPC: ${method}`)
    })
    const store = useAppStore()
    store.settings = { live_mod_detection: true, auto_low_consumption_mode: false }
    store.modRevision = 3

    await store.refreshRuntime()

    expect(invokeMock.mock.calls).toEqual([
      ['get_runtime_status'],
      ['scan_mods', false],
    ])
  })

  it('ends the game process and immediately clears the running state', async () => {
    invokeMock.mockResolvedValue({
      process_ids: [42],
      runtime: { running: false, mod_revision: 4 },
    })
    const store = useAppStore()
    store.runtime = { running: true, mod_revision: 4 }

    await store.terminateGame()

    expect(invokeMock).toHaveBeenCalledWith('terminate_game')
    expect(store.runtime).toEqual({ running: false, mod_revision: 4 })
    expect(store.busy).toBe('')
  })

  it('refreshes Workshop metadata without taking the global busy lock', async () => {
    let finish
    invokeMock.mockImplementation(method => {
      if (method !== 'refresh_workshop_metadata') throw new Error(`Unexpected RPC: ${method}`)
      return new Promise(resolve => { finish = resolve })
    })
    const store = useAppStore()
    store.runtime = { running: false }

    const pending = store.refreshWorkshopInBackground()
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
    expect(store.workshopRefreshing).toBe(true)
    expect(invokeMock).toHaveBeenCalledWith('refresh_workshop_metadata', null, 'warhammer3', true)
    expect(store.busy).toBe('')
    finish(emptyScan(0))
    await pending
    expect(store.workshopRefreshing).toBe(false)
  })

  it('keeps manual Workshop refresh as an explicit full refresh', async () => {
    invokeMock.mockResolvedValue(emptyScan(0))
    const store = useAppStore()
    await store.refreshWorkshopInBackground(null, true)
    expect(invokeMock).toHaveBeenCalledWith('refresh_workshop_metadata', null, 'warhammer3')
  })

  it('keeps discovering MODs and queues their metadata while another metadata request is slow', async () => {
    const first = { id: 'first', source: 'workshop', workshop_id: '111', pack_name: 'first.pack' }
    const second = { id: 'second', source: 'workshop', workshop_id: '222', pack_name: 'second.pack' }
    let finishFirst
    const metadataCalls = []
    invokeMock.mockImplementation(async (method, ids) => {
      if (method === 'refresh_workshop_metadata') {
        metadataCalls.push(ids)
        if (ids[0] === '111') return new Promise(resolve => { finishFirst = resolve })
        return { ...emptyScan(4), mods: [first, { ...second, display_name: 'Second MOD title' }] }
      }
      if (method === 'scan_mods') return { ...emptyScan(4), mods: [first, second] }
      return {}
    })
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3', fetch_workshop_metadata: true }
    store.mods = [first]
    const pending = store.refreshWorkshopInBackground(['111'])
    await vi.waitFor(() => expect(finishFirst).toBeTypeOf('function'))
    await store.refreshModsInBackground()
    expect(store.mods.map(mod => mod.id)).toEqual(['first', 'second'])
    expect(store.liveModRefreshing).toBe(false)
    expect(metadataCalls).toEqual([['111']])
    finishFirst({ ...emptyScan(3), mods: [first] })
    await pending
    expect(metadataCalls).toEqual([['111'], ['222']])
    expect(store.mods.map(mod => mod.id)).toEqual(['first', 'second'])
    expect(store.mods[1].display_name).toBe('Second MOD title')
    expect(store.workshopRefreshing).toBe(false)
  })

  it('ignores a stale Workshop ownership response after a newer menu request', async () => {
    let resolveFirst
    let resolveSecond
    invokeMock.mockImplementation((method, modIds) => {
      if (method !== 'get_workshop_update_eligibility') throw new Error(`Unexpected RPC: ${method}`)
      return new Promise(resolve => {
        if (modIds[0] === 'first') resolveFirst = resolve
        else resolveSecond = resolve
      })
    })
    const store = useAppStore()

    const first = store.refreshWorkshopUpdateEligibility(['first'])
    const second = store.refreshWorkshopUpdateEligibility(['second'])
    resolveSecond({ eligible_mod_ids: ['second'] })
    await second
    resolveFirst({ eligible_mod_ids: ['first'] })
    await first

    expect([...store.workshopUpdateEligibility]).toEqual(['second'])
  })

  it('reuses a successful Workshop ownership response for repeated menu openings', async () => {
    invokeMock.mockResolvedValue({ eligible_mod_ids: ['owned'] })
    const store = useAppStore()

    await store.refreshWorkshopUpdateEligibility(['owned'])
    await store.refreshWorkshopUpdateEligibility(['owned'])

    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect([...store.workshopUpdateEligibility]).toEqual(['owned'])
  })
})
