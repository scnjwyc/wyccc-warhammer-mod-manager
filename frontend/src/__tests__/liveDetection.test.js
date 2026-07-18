// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('../bridge', () => ({ invoke: invokeMock }))

import { useAppStore } from '../store'

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

  it('does not scan while the game is running', async () => {
    invokeMock.mockResolvedValue({ running: true, mod_revision: 4 })
    const store = useAppStore()
    store.settings = { live_mod_detection: true }
    store.modRevision = 3

    await store.refreshRuntime()

    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(invokeMock).toHaveBeenCalledWith('get_runtime_status')
  })

  it('refreshes Workshop metadata without taking the global busy lock', async () => {
    let finish
    invokeMock.mockImplementation(method => {
      if (method !== 'scan_mods') throw new Error(`Unexpected RPC: ${method}`)
      return new Promise(resolve => { finish = resolve })
    })
    const store = useAppStore()
    store.runtime = { running: false }

    const pending = store.refreshWorkshopInBackground()
    await vi.waitFor(() => expect(store.workshopRefreshing).toBe(true))
    expect(store.busy).toBe('')
    finish(emptyScan(0))
    await pending
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
})
