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

  it('selects every id supplied by the focused visible list', async () => {
    const store = useAppStore()
    store.mods = ['a', 'b', 'c'].map(id => ({ id, pack_name: `${id}.pack` }))

    await store.selectAllMods(['c', 'a', 'missing'])

    expect(store.selectedIds).toEqual(['c', 'a'])
    expect(store.selectedId).toBe('c')
    expect(store.selectionAnchorId).toBe('c')
  })

  it('creates a save playset and persists the exact save order without subscribing', async () => {
    const store = useAppStore()
    store.mods = [
      { id: 'data:first', pack_name: 'first.pack', source: 'data', sources: ['data'] },
      { id: 'steam:second', pack_name: 'second.pack', source: 'workshop', sources: ['workshop'] },
      { id: 'steam:extra', pack_name: 'extra.pack', source: 'workshop', sources: ['workshop'] },
    ]
    store.activeIds = ['steam:extra']
    store.orderToken = 'before-import'
    const importedPlayset = {
      id: 'save-playset',
      name: '存档campaign.save',
      mod_ids: ['steam:second', 'data:first'],
    }
    invokeMock.mockImplementation(async method => ({
      get_save_mods: {
        save: { name: 'campaign.save' },
        pack_names: ['SECOND.PACK', 'missing.pack', 'first.pack'],
      },
      create_playset: {
        playsets: [importedPlayset],
        current_playset: importedPlayset,
        ordered_mod_ids: ['steam:second', 'data:first'],
        missing_mod_ids: [],
      },
      update_playset: {
        playsets: [importedPlayset],
        current_playset: importedPlayset,
      },
      save_load_order: {
        order_token: 'after-import',
        backup: null,
      },
    }[method]))

    const comparison = await store.compareSaveMods('campaign.save')
    expect(comparison.saveOnly.map(item => item.packName)).toEqual(['SECOND.PACK', 'missing.pack', 'first.pack'])
    expect(comparison.currentOnly.map(item => item.packName)).toEqual(['extra.pack'])
    expect(comparison.shared).toEqual([])

    const imported = await store.createPlaysetFromSave('campaign.save')
    expect(store.currentPlaysetId).toBe('save-playset')
    expect(store.activeIds).toEqual(['steam:second', 'data:first'])
    expect(imported.playset.name).toBe('存档campaign.save')
    expect(imported.missingPackNames).toEqual(['missing.pack'])
    expect(invokeMock).toHaveBeenCalledWith(
      'create_playset',
      '存档campaign.save',
      ['steam:second', 'data:first'],
    )
    expect(invokeMock).toHaveBeenCalledWith(
      'update_playset',
      'save-playset',
      ['steam:second', 'data:first'],
    )
    expect(invokeMock).toHaveBeenCalledWith(
      'save_load_order',
      ['steam:second', 'data:first'],
      'before-import',
    )
    expect(invokeMock).not.toHaveBeenCalledWith('subscribe_workshop_items', expect.anything())
  })

  it('creates a distinct suffixed playset when the save was imported before', async () => {
    const store = useAppStore()
    store.mods = [{ id: 'first', pack_name: 'first.pack', source: 'data' }]
    store.playsets = [
      { id: 'existing-1', name: '存档campaign.save', mod_ids: [] },
      { id: 'existing-2', name: '存档campaign.save (2)', mod_ids: [] },
    ]
    store.recordCurrentPlaysetChange = vi.fn()
    invokeMock.mockImplementation(async method => {
      if (method === 'get_save_mods') {
        return { save: { name: 'campaign.save' }, pack_names: ['first.pack'] }
      }
      if (method === 'create_playset') {
        const playset = { id: 'new', name: '存档campaign.save (3)', mod_ids: ['first'] }
        return {
          playsets: [...store.playsets, playset],
          current_playset: playset,
          ordered_mod_ids: ['first'],
          missing_mod_ids: [],
        }
      }
      return {}
    })

    await store.createPlaysetFromSave('campaign.save')

    expect(invokeMock).toHaveBeenCalledWith('create_playset', '存档campaign.save (3)', ['first'])
  })

  it('copies selected primary MOD paths as a deduplicated newline list', async () => {
    const store = useAppStore()
    store.mods = [
      { id: 'a', path: 'X:/data/a.pack' },
      { id: 'b', path: 'X:/data/b.pack' },
      { id: 'duplicate', path: 'X:/data/a.pack' },
    ]
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue() } })

    await store.copyModPaths(['b', 'a', 'duplicate'])

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('X:/data/b.pack\nX:/data/a.pack')
  })

  it('generates user data sequentially and continues after a failed MOD', async () => {
    const store = useAppStore()
    store.mods = ['a', 'b', 'c'].map(id => ({ id, pack_name: `${id}.pack` }))
    invokeMock
      .mockResolvedValueOnce({ id: 'a', pack_name: 'a.pack', alias: 'A', notes: 'first' })
      .mockRejectedValueOnce(new Error('provider unavailable'))
      .mockResolvedValueOnce({ id: 'c', pack_name: 'c.pack', alias: 'C', notes: 'third' })

    await expect(store.generateModUserDataMany(['a', 'b', 'a', 'c'])).resolves.toEqual({
      succeeded: ['a', 'c'],
      failed: ['b'],
    })

    expect(invokeMock.mock.calls).toEqual([
      ['generate_mod_user_data', 'a'],
      ['generate_mod_user_data', 'b'],
      ['generate_mod_user_data', 'c'],
    ])
    expect(store.mods.map(mod => mod.alias || '')).toEqual(['A', '', 'C'])
  })

  it('keeps enabled and disabled MOD searches independently highlighted and filtered', async () => {
    const store = useAppStore()
    store.settings = {
      language: 'zh-CN',
      active_search_highlight_mode: true,
      inactive_search_highlight_mode: false,
    }
    store.mods = [
      { id: 'active-match', effective_name: 'Alpha', pack_name: 'alpha.pack' },
      { id: 'active-muted', effective_name: 'Gamma', pack_name: 'gamma.pack' },
      { id: 'inactive-muted', effective_name: 'Beta', pack_name: 'beta.pack' },
      { id: 'inactive-match', effective_name: 'Alphabet', pack_name: 'alphabet.pack' },
    ]
    store.activeIds = ['active-match', 'active-muted']
    store.activeSearchTokens = [{ type: 'text', value: 'Alpha' }]
    store.inactiveSearchTokens = [{ type: 'text', value: 'Beta' }]
    invokeMock.mockImplementation(method => {
      if (method === 'set_search_highlight_mode') {
        return Promise.resolve({
          settings: {
            language: 'zh-CN',
            active_search_highlight_mode: false,
            inactive_search_highlight_mode: false,
          },
        })
      }
      return Promise.resolve({ items: [] })
    })

    expect(store.activeMods.map(mod => mod.id)).toEqual(['active-match', 'active-muted'])
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['inactive-muted'])
    expect(store.activeSearchMatchIds).toEqual(['active-match'])
    expect(store.inactiveSearchMatchIds).toEqual(['inactive-muted'])

    await store.setActiveSearchHighlightMode(false)
    expect(invokeMock).toHaveBeenCalledWith('set_search_highlight_mode', false, 'active')
    expect(store.settings.active_search_highlight_mode).toBe(false)
    expect(store.settings.inactive_search_highlight_mode).toBe(false)
    expect(store.activeMods.map(mod => mod.id)).toEqual(['active-match'])
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['inactive-muted'])
    expect(store.activeIds).toEqual(['active-match', 'active-muted'])
    expect(store.mods).toHaveLength(4)
  })

  it('sorts enabled and disabled MOD lists independently', () => {
    const store = useAppStore()
    store.mods = [
      { id: 'active-new', pack_name: 'z-active.pack', updated_at: 200 },
      { id: 'active-old', pack_name: 'a-active.pack', updated_at: 100 },
      { id: 'inactive-old', pack_name: 'y-inactive.pack', updated_at: 100 },
      { id: 'inactive-new', pack_name: 'b-inactive.pack', updated_at: 300 },
    ]
    store.activeIds = ['active-new', 'active-old']

    store.setActiveSortMode('updated')

    expect(store.activeMods.map(mod => mod.id)).toEqual(['active-new', 'active-old'])
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['inactive-old', 'inactive-new'])
    expect(store.activeSortMode).toBe('updated')
    expect(store.inactiveSortMode).toBe('priority')

    store.setInactiveSortMode('updated')

    expect(store.activeMods.map(mod => mod.id)).toEqual(['active-new', 'active-old'])
    expect(store.inactiveMods.map(mod => mod.id)).toEqual(['inactive-new', 'inactive-old'])
  })

  it('derives hidden MOD visibility from the persisted basic setting', () => {
    const store = useAppStore()
    store.mods = [
      { id: 'visible', effective_name: 'Visible', pack_name: 'visible.pack' },
      { id: 'hidden', effective_name: 'Hidden', pack_name: 'hidden.pack', hidden: true },
    ]
    store.settings = { show_hidden_mods: false }

    expect(store.inactiveDisplayMods.map(mod => mod.id)).toEqual(['visible'])
    store.settings.show_hidden_mods = true
    expect(store.inactiveDisplayMods.map(mod => mod.id)).toEqual(['visible', 'hidden'])
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

  it('keeps backend dependency warnings while the enabled list changes', () => {
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

    store.applyMissingDependencyWarnings({
      a: [{ code: 'missing_dependency', severity: 'error', message: '缺少依赖：a-base.pack' }],
    })

    store.enable('a')
    expect(store.mods[0].warnings.map(item => item.code)).toEqual(['missing_dependency'])
    expect(store.mods[1].warnings).toEqual([])
    expect(store.warningItems.map(item => item.modId)).toEqual(['a'])

    store.enable('b')
    expect(store.warningItems.map(item => item.modId)).toEqual(['a'])

    store.applyMissingDependencyWarnings({
      a: [{ code: 'missing_dependency', severity: 'error', message: '缺少依赖：a-base.pack' }],
      b: [{ code: 'missing_dependency', severity: 'error', message: '缺少依赖：b-base.pack' }],
    })
    expect(store.warningItems.map(item => item.modId)).toEqual(['a', 'b'])

    const refreshWarnings = vi.spyOn(store, 'refreshMissingDependencyWarnings')
    store.reorder('a', 'b')
    expect(refreshWarnings).toHaveBeenCalled()

    store.disable('a')
    expect(store.mods[0].warnings.map(item => item.code)).toEqual(['missing_dependency'])
    expect(store.mods[1].warnings.map(item => item.code)).toEqual(['missing_dependency'])
    expect(store.warningItems.map(item => item.modId)).toEqual(['b'])

    store.applyPlaysetPayload({
      playsets: [{ id: 'other', name: 'Other', mod_ids: ['a'] }],
      current_playset: { id: 'other', name: 'Other', mod_ids: ['a'] },
      ordered_mod_ids: ['a'],
      missing_mod_ids: [],
      missing_dependency_warnings: {
        a: [{ code: 'missing_dependency', severity: 'error', message: '缺少依赖：a-base.pack' }],
      },
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

  it('subscribes to workshop dependencies and enables installed or pending items', async () => {
    const store = useAppStore()
    store.mods = [
      { id: 'dependent', pack_name: 'dependent.pack', workshop_id: '10' },
      { id: 'installed-base', pack_name: 'base.pack', workshop_id: '20' },
    ]
    store.activeIds = ['dependent']
    store.recordCurrentPlaysetChange = vi.fn()
    invokeMock.mockResolvedValue({ subscribed: ['30'], already_subscribed: [] })

    const result = await store.subscribeAndEnableMissingDependencies([{
      code: 'missing_dependency',
      dependencies: [
        { kind: 'pack', id: 'base.pack', name: 'base.pack' },
        { kind: 'workshop', id: '30', name: 'Missing Workshop' },
      ],
    }])

    expect(invokeMock).toHaveBeenCalledWith('subscribe_workshop_items', ['30'])
    expect(store.activeIds).toContain('installed-base')
    expect(store.missingEnabledIds).toContain('pending:steam:30:')
    expect(store.recordCurrentPlaysetChange).toHaveBeenCalledTimes(1)
    expect(result.pending).toEqual(['pending:steam:30:'])
  })
})
