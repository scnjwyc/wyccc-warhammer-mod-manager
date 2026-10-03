import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import { useAppStore } from '../store'
import { compareModLists } from '../modListComparison'
import LastLaunchComparisonModal from '../components/LastLaunchComparisonModal.vue'
import LaunchHistoryModal from '../components/LaunchHistoryModal.vue'
import App from '../App.vue'
import { applyInterfaceLanguage, localizeBackendMessage, t } from '../languages'

const mods = names => names.map(name => ({ id: name, pack_name: `${name}.pack`, effective_name: name }))
const snapshot = names => ({ id: 'record-1', available: true, started_at: 123, mods: mods(names) })

beforeEach(() => { setActivePinia(createPinia()); invokeMock.mockReset() })

describe('last launch comparison', () => {
  it('localizes unavailable history errors in all built-in languages', () => {
    for (const language of ['zh-CN', 'en-US', 'ko-KR', 'ru-RU', 'ja-JP', 'es-ES']) {
      applyInterfaceLanguage(language)
      expect(localizeBackendMessage('launchHistory.notFound')).toBe(t('launchHistory.notFound'))
      expect(localizeBackendMessage('launchHistory.notFound')).not.toContain('launchHistory.notFound')
    }
    applyInterfaceLanguage('zh-CN')
  })
  it('compares the real launch snapshot against the real rescanned enabled list', async () => {
    const root = resolve(process.cwd(), '..')
    const localPython = resolve(root, process.platform === 'win32'
      ? '.venv-build/Scripts/python.exe' : '.venv-build/bin/python')
    const python = process.env.PYTHON || (existsSync(localPython) ? localPython : 'python')
    const fixture = JSON.parse(execFileSync(python, ['-m', 'tests.last_launch_bridge_fixture'], {
      cwd: root, encoding: 'utf8',
    }))
    expect(fixture.snapshot.ok).toBe(true)
    expect(fixture.scan.ok).toBe(true)
    const store = useAppStore()
    store.settings = fixture.bootstrap.data.settings
    store.mods = fixture.scan.data.mods
    store.activeIds = fixture.scan.data.enabled_order
    invokeMock.mockResolvedValue(fixture.snapshot.data)
    const result = await store.compareLaunchRecord(fixture.snapshot.data.id)
    expect(result.added.map(item => item.packName)).toEqual(['new.pack'])
    expect(result.removed.map(item => item.packName)).toEqual(['a.pack'])
    expect(result.reorderedCount).toBe(2)
    invokeMock.mockResolvedValue(fixture.loaded.data)
    await store.loadLaunchRecord(fixture.snapshot.data.id)
    expect(store.activeIds).toEqual(fixture.loaded.data.ordered_mod_ids)
    expect(store.dirty).toBe(false)
    expect(invokeMock.mock.calls.map(call => call[0])).toEqual(['get_launch_record', 'load_launch_record'])
  })

  it('compares additions and removals against enabled MODs only', async () => {
    const store = useAppStore()
    store.mods = mods(['a', 'b', 'c', 'disabled'])
    store.activeIds = ['b', 'c']
    invokeMock.mockResolvedValue(snapshot(['a', 'b']))
    const result = await store.compareLaunchRecord('record-1')
    expect(result.removed.map(item => item.packName)).toEqual(['a.pack'])
    expect(result.added.map(item => item.packName)).toEqual(['c.pack'])
    expect(result.shared.map(item => item.packName)).toEqual(['b.pack'])
    expect(result.reorderedCount).toBe(0)
    expect(invokeMock).toHaveBeenCalledExactlyOnceWith('get_launch_record', 'record-1')
    expect(store.activeIds).toEqual(['b', 'c'])
  })

  it('recognizes case-insensitive filenames and a changed source id', () => {
    const result = compareModLists(snapshot(['a']), [{ id: 'workshop:new', pack_name: 'A.PACK' }])
    expect(result.identical).toBe(true)
  })

  it('detects real reorder but not position shifts caused by adding or removing MODs', () => {
    const shifted = compareModLists(snapshot(['a', 'b', 'c']), mods(['new', 'b', 'c']))
    expect(shifted.reorderedCount).toBe(0)
    const reordered = compareModLists(snapshot(['a', 'b', 'c']), mods(['c', 'b', 'a']))
    expect(reordered.reorderedCount).toBe(2)
    expect(reordered.shared[0]).toMatchObject({ previousPosition: 1, currentPosition: 3, reordered: true })
  })

  it('distinguishes no record from launching with zero MODs', () => {
    expect(compareModLists({ available: false }, mods(['a']))).toEqual({ available: false })
    expect(compareModLists(snapshot([]), mods(['a'])).added).toHaveLength(1)
    expect(compareModLists(snapshot([]), [])).toMatchObject({ available: true, identical: true })
  })

  it('keeps the historical name of removed MODs and shows order changes', () => {
    const wrapper = mount(LastLaunchComparisonModal, { props: {
      open: true, comparison: compareModLists(snapshot(['removed', 'a', 'b']), mods(['b', 'a', 'new'])),
    } })
    expect(wrapper.get('[data-testid="removed-group"]').text()).toContain('removed')
    expect(wrapper.get('[data-testid="removed-group"]').text()).not.toContain('removed.pack')
    expect(wrapper.get('[data-testid="added-group"]').text()).toContain('new')
    expect(wrapper.get('[data-testid="shared-group"]').text()).toContain('与其他 MOD 的先后关系变化')
    expect(wrapper.get('[data-testid="launch-comparison-summary"]').text()).toContain('顺序变化 2 个')
  })

  it('shows the first-launch message and allows closing the dialog', async () => {
    const wrapper = mount(LastLaunchComparisonModal, { props: { open: true, comparison: { available: false } } })
    expect(wrapper.get('[data-testid="no-launch-record"]').text()).toContain('尚无')
    expect(wrapper.find('[data-testid="shared-group"]').exists()).toBe(false)
    await wrapper.get('.modal-footer button').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('discards a delayed snapshot after switching games', async () => {
    let finish
    invokeMock.mockReturnValue(new Promise(resolve => { finish = resolve }))
    const store = useAppStore()
    const pending = store.compareLaunchRecord('record-1')
    store.beginGameContextChange()
    finish(snapshot(['old-game']))
    expect(await pending).toBeNull()
  })

  it('opens history and compares the selected record from the button left of the save list', async () => {
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3', language: 'zh-CN' }
    store.pathHealth = { game_ready: true }
    store.mods = mods(['a'])
    store.activeIds = ['a']
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    vi.spyOn(store, 'refreshRuntime').mockResolvedValue({})
    invokeMock.mockImplementation(async method => {
      if (method === 'get_launch_record') return snapshot(['a'])
      if (method === 'list_launch_history') return { items: [{ id: 'record-1', started_at: 123, mod_count: 1 }] }
      return {}
    })
    const wrapper = mount(App, { global: { stubs: {
      ModList: true, ModDetails: true, SettingsModal: true, ModDiagnosticsModal: true,
    } } })
    try {
      await flushPromises()
      const button = wrapper.get('[data-testid="launch-history-button"]')
      expect(button.text()).toBe('启动记录')
      expect(button.element.nextElementSibling.dataset.testid).toBe('save-list-button')
      expect(button.classes()).toContain('save-list-button')
      await button.trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-testid="launch-history-mods"]').text()).toContain('a')
      expect(wrapper.get('[data-testid="launch-history-mods"]').text()).not.toContain('a.pack')
      await wrapper.get('[data-testid="launch-history-compare"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-testid="launch-comparison-summary"]').text()).toContain('与该记录一致')
    } finally { wrapper.unmount() }
  })

  it('lists every record and routes selection and load by its own id', async () => {
    const wrapper = mount(LaunchHistoryModal, { props: {
      open: true,
      records: [{ id: 'newest', started_at: 200, mod_count: 1 }, { id: 'older', started_at: 100, mod_count: 1 }],
      selected: { ...snapshot(['a']), id: 'older' },
    } })
    expect(wrapper.findAll('[data-testid="launch-history-record"]')).toHaveLength(2)
    await wrapper.findAll('[data-testid="launch-history-record"]')[1].trigger('click')
    expect(wrapper.emitted('select')).toEqual([['older']])
    await wrapper.get('[data-testid="launch-history-load"]').trigger('click')
    expect(wrapper.emitted('load')).toEqual([['older']])
    await wrapper.setProps({ running: true })
    expect(wrapper.get('[data-testid="launch-history-load"]').element.disabled).toBe(true)
    expect(wrapper.get('[data-testid="launch-history-compare"]').element.disabled).toBe(false)
  })

  it('applies a saved load response once and keeps the list on invalid responses', async () => {
    const store = useAppStore()
    store.activeIds = ['a']
    store.mods = mods(['a', 'b'])
    store.orderToken = 'before'
    invokeMock.mockResolvedValue({ ordered_mod_ids: ['b', 'a'], order_token: 'after', missing_mod_ids: [] })
    await store.loadLaunchRecord('older')
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(invokeMock).toHaveBeenCalledExactlyOnceWith('load_launch_record', 'older', 'before')
    invokeMock.mockResolvedValue({ current_playset: { mod_ids: [] } })
    await expect(store.loadLaunchRecord('bad-response')).rejects.toThrow()
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(store.orderToken).toBe('after')
  })
})
