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

  it('supports temporary inactive ordering and batch moves between both lists', () => {
    const store = useAppStore()
    store.mods = ['a', 'b', 'c', 'd', 'e'].map(id => ({ id, pack_name: `${id}.pack` }))
    store.activeIds = ['a', 'b']
    store.inactiveOrderIds = ['a', 'b', 'c', 'd', 'e']
    store.recordCurrentPlaysetChange = vi.fn()

    store.handleModDrop({
      source: 'active',
      target: 'inactive',
      ids: ['b'],
      draggedId: 'b',
      targetId: 'd',
      targetOrder: ['c', 'd', 'e'],
    })
    expect(store.activeIds).toEqual(['a'])
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['c', 'b', 'd', 'e'])

    store.handleModDrop({
      source: 'inactive',
      target: 'active',
      ids: ['c', 'e'],
      draggedId: 'c',
      targetId: 'a',
      sourceOrder: ['c', 'b', 'd', 'e'],
    })
    expect(store.activeIds).toEqual(['c', 'e', 'a'])
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['b', 'd'])
    expect(store.recordCurrentPlaysetChange).toHaveBeenCalledTimes(2)

    store.handleModDrop({
      source: 'inactive',
      target: 'inactive',
      ids: ['d'],
      draggedId: 'd',
      targetId: 'b',
      targetOrder: ['b', 'd'],
    })
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['d', 'b'])
    expect(store.recordCurrentPlaysetChange).toHaveBeenCalledTimes(2)
  })

  it('dismisses an ignorable dependency refresh notice for the current session', () => {
    const store = useAppStore()
    store.warnings = [{
      code: 'workshop_dependency_refresh',
      severity: 'warning',
      message: 'Steam 暂时无法读取部分工坊依赖，已使用已有缓存；缺失依赖结果可能不是最新状态',
      ignorable: true,
    }]

    expect(store.warningItems[0]).toMatchObject({
      code: 'workshop_dependency_refresh',
      ignorable: true,
    })
    store.ignoreScanWarning('workshop_dependency_refresh')
    expect(store.warningCount).toBe(0)
  })

  it('rechecks missing dependencies whenever the enabled list changes', () => {
    const store = useAppStore()
    store.mods = [
      {
        id: 'a',
        pack_name: 'a.pack',
        effective_name: 'A',
        missing_dependencies: [{ kind: 'pack', id: 'a-base.pack', name: 'a-base.pack' }],
        warnings: [],
        ignored_warning_codes: [],
      },
      {
        id: 'b',
        pack_name: 'b.pack',
        effective_name: 'B',
        missing_dependencies: [{ kind: 'pack', id: 'b-base.pack', name: 'b-base.pack' }],
        warnings: [],
        ignored_warning_codes: [],
      },
    ]
    store.recordCurrentPlaysetChange = vi.fn()
    store.replaceActiveIds([])

    store.enable('a')
    expect(store.mods[0].warnings.map(item => item.code)).toEqual(['missing_dependency'])
    expect(store.mods[1].warnings).toEqual([])
    expect(store.warningItems.map(item => item.modId)).toEqual(['a'])

    store.enable('b')
    expect(store.warningItems.map(item => item.modId)).toEqual(['a', 'b'])

    const refreshWarnings = vi.spyOn(store, 'refreshMissingDependencyWarnings')
    store.reorder('a', 'b')
    expect(refreshWarnings).toHaveBeenCalled()

    store.disable('a')
    expect(store.mods[0].warnings).toEqual([])
    expect(store.mods[1].warnings.map(item => item.code)).toEqual(['missing_dependency'])
    expect(store.warningItems.map(item => item.modId)).toEqual(['b'])

    store.applyPlaysetPayload({
      playsets: [{ id: 'other', name: 'Other', mod_ids: ['a'] }],
      current_playset: { id: 'other', name: 'Other', mod_ids: ['a'] },
      ordered_mod_ids: ['a'],
      missing_mod_ids: [],
    })
    expect(store.mods[0].warnings.map(item => item.code)).toEqual(['missing_dependency'])
    expect(store.mods[1].warnings).toEqual([])
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
