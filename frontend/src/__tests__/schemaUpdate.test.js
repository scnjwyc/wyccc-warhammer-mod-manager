// @vitest-environment jsdom
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import ModContextMenu from '../components/ModContextMenu.vue'
import SchemaUpdateModal from '../components/SchemaUpdateModal.vue'
import { useAppStore } from '../store'
import { applyInterfaceLanguage, localizeBackendMessage, t } from '../languages'
import App from '../App.vue'
import ModList from '../components/ModList.vue'

const mod = { id: 'a', effective_name: 'A', pack_name: 'a.pack', path: 'G:/a.pack', source: 'data' }
const report = {
  updated_count: 1, unchanged_count: 0, failed_count: 1, partial_count: 0, schema: { cached: true },
  results: [
    { mod_id: 'a', name: 'A', path: 'G:/a.pack', status: 'updated', backup_path: 'G:/backup/a.pack.bak',
      tables: [{ path: 'db/test/x', from_version: 1, to_version: 2, rows: 3, reset_values: 1 }], skipped: [] },
    { mod_id: 'b', name: 'B', status: 'failed', error: 'db/test/b: schemaUpdate.decodeFailed' },
  ],
  scan: { game_id: 'warhammer3', mods: [mod], enabled_order: ['a'] },
}

beforeEach(() => { setActivePinia(createPinia()); invokeMock.mockReset(); applyInterfaceLanguage('zh-CN') })

describe('table schema update', () => {
  it('routes the current context selection through App and keeps the result visible', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAppStore()
    store.settings = { selected_game: 'warhammer3', language: 'zh-CN' }
    store.pathHealth = { game_ready: true }
    store.mods = [mod, { ...mod, id: 'b', pack_name: 'b.pack' }]
    store.selectedIds = ['a', 'b']
    store.selectedId = 'a'
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    vi.spyOn(store, 'refreshRuntime').mockResolvedValue({})
    const update = vi.spyOn(store, 'updateModTableSchemas').mockResolvedValue(report)
    invokeMock.mockResolvedValue({})
    const wrapper = shallowMount(App, { global: { plugins: [pinia], stubs: {
      ModContextMenu: false, SchemaUpdateModal: false,
    } } })
    try {
      await flushPromises()
      wrapper.findAllComponents(ModList)[0].vm.$emit('context-menu', { mod, x: 20, y: 20 })
      await wrapper.vm.$nextTick()
      await wrapper.get('[data-testid="context-update-schemas"]').trigger('click')
      await flushPromises()
      expect(update).toHaveBeenCalledWith(['a', 'b'])
      expect(wrapper.get('[data-testid="schema-update-modal"]').text()).toContain('已更新 1 个')
      expect(wrapper.find('[data-testid="mod-context-menu"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('offers a batch action and blocks it while busy or the game is running', async () => {
    const wrapper = mount(ModContextMenu, { props: { open: true, mod, selectionCount: 2 } })
    const button = wrapper.get('[data-testid="context-update-schemas"]')
    expect(button.text()).toContain('更新表结构')
    expect(button.text()).toContain('2')
    await button.trigger('click')
    expect(wrapper.emitted('action')[0][0]).toMatchObject({ action: 'update-table-schemas', mod })
    await wrapper.setProps({ gameRunning: true })
    expect(button.element.disabled).toBe(true)
    await wrapper.setProps({ gameRunning: false, busy: true })
    expect(button.element.disabled).toBe(true)
    await wrapper.setProps({ busy: false, packActions: false })
    expect(wrapper.find('[data-testid="context-update-schemas"]').exists()).toBe(false)
  })

  it('updates selected IDs in one RPC and preserves dirty enablement and order during refresh', async () => {
    const store = useAppStore()
    store.mods = [mod, { ...mod, id: 'b', pack_name: 'b.pack' }]
    store.activeIds = ['b', 'a']
    store.selectedId = 'a'
    store.selectedIds = ['a', 'b']
    store.dirty = true
    const scan = { ...report.scan, mods: store.mods, enabled_order: ['a', 'b'] }
    invokeMock.mockImplementation(async method => method === 'update_mod_table_schemas' ? { ...report, scan } : {})
    const result = await store.updateModTableSchemas(['a', 'b', 'a'])
    expect(invokeMock).toHaveBeenCalledWith('update_mod_table_schemas', ['a', 'b'], 'warhammer3')
    expect(invokeMock.mock.calls.some(([method]) => method === 'update_playset' || method === 'save_load_order')).toBe(false)
    expect(store.activeIds).toEqual(['b', 'a'])
    expect(store.selectedIds).toEqual(['a', 'b'])
    expect(store.dirty).toBe(true)
    expect(store.busy).toBe('')
    expect(result.failed_count).toBe(1)
  })

  it('shows mixed results, backup locations, conversion defaults and cached schema warning', () => {
    const wrapper = mount(SchemaUpdateModal, { props: { open: true, report } })
    expect(wrapper.findAll('article')).toHaveLength(2)
    expect(wrapper.text()).toContain('G:/backup/a.pack.bak')
    expect(wrapper.text()).toContain('v1 → v2')
    expect(wrapper.text()).toContain('1 个值无法转换')
    expect(wrapper.text()).toContain('缓存')
    expect(wrapper.text()).toContain('原 Pack 未修改')
    expect(wrapper.text()).not.toContain('schemaUpdate.decodeFailed')
    expect(wrapper.get('details').attributes('open')).toBeDefined()
  })

  it('shows the bundled schema source without a network failure warning in every language', () => {
    for (const language of ['zh-CN', 'en-US', 'ko-KR', 'ru-RU', 'ja-JP', 'es-ES']) {
      applyInterfaceLanguage(language)
      const wrapper = mount(SchemaUpdateModal, { props: { open: true,
        report: { ...report, schema: { cached: false, bundled: true }, results: [] } } })
      expect(wrapper.text()).toContain(t('schemaUpdate.bundled'))
      expect(wrapper.text()).not.toContain(t('schemaUpdate.cached'))
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      wrapper.unmount()
    }
  })

  it('keeps a running update visible and closes only when it has finished', async () => {
    const wrapper = mount(SchemaUpdateModal, { props: { open: true, pending: true } })
    await wrapper.get('.modal-backdrop').trigger('mousedown')
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(wrapper.get('footer button').element.disabled).toBe(true)
    await wrapper.setProps({ pending: false, error: 'schemaUpdate.downloadFailed' })
    expect(wrapper.get('[role="alert"]').text()).toContain('检查网络')
    await wrapper.get('footer button').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('localizes structured errors including table paths in all six languages', () => {
    for (const language of ['zh-CN', 'en-US', 'ko-KR', 'ru-RU', 'ja-JP', 'es-ES']) {
      applyInterfaceLanguage(language)
      const error = localizeBackendMessage('db/test/x: schemaUpdate.unknownVersion')
      expect(error).toContain('db/test/x')
      expect(error).not.toContain('schemaUpdate.')
      expect(localizeBackendMessage('schemaUpdate.bundledGameVersion')).toBe(t('schemaUpdate.bundledGameVersion'))
    }
    applyInterfaceLanguage('zh-CN')
  })
})
