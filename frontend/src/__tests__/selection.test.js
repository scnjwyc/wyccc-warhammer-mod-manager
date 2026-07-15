// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))

import { useAppStore } from '../store'

describe('anchored mod selection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    invokeMock.mockReset()
    invokeMock.mockResolvedValue({ url: '' })
  })

  it('supports plain, Ctrl, Shift and Ctrl+Shift selection', async () => {
    const store = useAppStore()
    store.mods = ['a', 'b', 'c', 'd'].map(id => ({ id, pack_name: `${id}.pack` }))
    const orderedIds = ['a', 'b', 'c', 'd']

    await store.selectMod({ id: 'b', orderedIds })
    expect(store.selectedIds).toEqual(['b'])

    await store.selectMod({ id: 'd', ctrlKey: true, orderedIds })
    expect(store.selectedIds).toEqual(['b', 'd'])

    await store.selectMod({ id: 'b', shiftKey: true, orderedIds })
    expect(store.selectedIds).toEqual(['b', 'c', 'd'])

    await store.selectMod({ id: 'c', ctrlKey: true, orderedIds })
    expect(store.selectedIds).toEqual(['b', 'd'])

    await store.selectMod({ id: 'a', shiftKey: true, orderedIds })
    expect(store.selectedIds).toEqual(['a', 'b', 'c'])

    await store.selectMod({ id: 'd', ctrlKey: true, shiftKey: true, orderedIds })
    expect(store.selectedIds).toEqual(['a', 'b', 'c', 'd'])
    expect(store.selectedId).toBe('d')
  })

  it('moves a multi-selection as one ordered block', () => {
    const store = useAppStore()
    store.activeIds = ['a', 'b', 'c', 'd', 'e']

    store.moveManyToPosition(['b', 'd'], 1)
    expect(store.activeIds).toEqual(['b', 'd', 'a', 'c', 'e'])

    store.moveManyToPosition(['b', 'd'], store.activeIds.length)
    expect(store.activeIds).toEqual(['a', 'c', 'e', 'b', 'd'])
    expect(store.dirty).toBe(true)
  })

  it('persists an ignored warning category and immediately updates visible warnings', async () => {
    const store = useAppStore()
    store.mods = [{
      id: 'a',
      pack_name: 'a.pack',
      effective_name: 'A',
      warnings: [{ code: 'missing_dependency', severity: 'error', message: '缺少依赖' }],
      ignored_warning_codes: [],
    }]
    invokeMock.mockResolvedValueOnce({
      ...store.mods[0],
      warnings: [],
      ignored_warning_codes: ['missing_dependency'],
    })

    await store.setModWarningIgnored('a', 'missing_dependency', true)

    expect(invokeMock).toHaveBeenCalledWith(
      'set_mod_warning_ignored',
      'a',
      'missing_dependency',
      true,
    )
    expect(store.mods[0].warnings).toEqual([])
    expect(store.mods[0].ignored_warning_codes).toEqual(['missing_dependency'])
    expect(store.warningCount).toBe(0)
  })
})
