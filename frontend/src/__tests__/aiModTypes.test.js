import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))

import App from '../App.vue'
import ModContextMenu from '../components/ModContextMenu.vue'
import { useAppStore } from '../store'

describe('AI MOD type identification', () => {
  let pinia
  let store
  let wrapper
  const mod = (id, name = id) => ({
    id, pack_name: `${name}.pack`, display_name: name, effective_name: name,
    source: 'data', pack_type: 'mod', mod_type: 'unknown', mod_types: ['unknown'],
    alias: 'player title', notes: 'player notes', warnings: [],
  })

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useAppStore()
    store.settings = { selected_game: 'warhammer3', ai_enabled: true }
    store.pathHealth = { game_ready: true }
    store.mods = [mod('translation', '!!_nanu_dynamic_rors中文汉化'), mod('music'), mod('untouched')]
    store.modTypes = [
      { id: 'language', name: '语言包', built_in: true },
      { id: 'ui', name: 'UI', built_in: true },
      { id: 'custom:music', name: '音乐', built_in: false },
      { id: 'unknown', name: '未知', built_in: true },
    ]
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    invokeMock.mockReset()
    invokeMock.mockImplementation(async (method, id) => {
      if (method === 'recognize_mod_types') {
        const types = id === 'translation' ? ['language'] : ['ui', 'custom:music']
        return { ...store.modMap.get(id), mod_type: types[0], mod_types: types }
      }
      if (method === 'get_diagnostics_history') return []
      return {}
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    vi.restoreAllMocks()
  })

  it('places AI识别 directly below manual input and emits the selected action', async () => {
    wrapper = mount(ModContextMenu, {
      props: { open: true, mod: store.mods[0], types: store.modTypes, aiEnabled: true },
    })
    const buttons = wrapper.get('.type-submenu').findAll('button')
    expect(buttons.slice(0, 2).map(button => button.attributes('data-testid')))
      .toEqual(['context-manual-type', 'context-ai-recognize-types'])
    expect(buttons[1].text()).toBe('✦AI识别')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.emitted('action')[0][0]).toMatchObject({ action: 'ai-recognize-types', mod: store.mods[0] })
    await wrapper.setProps({ aiEnabled: false })
    expect(buttons[1].attributes('disabled')).toBeDefined()
    expect(buttons[1].attributes('title')).toContain('设置')
    await wrapper.setProps({ aiEnabled: true, busy: true })
    expect(buttons[1].attributes('disabled')).toBeDefined()
  })

  it('applies language and multiple custom labels through the actual right-click menu', async () => {
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    store.selectedIds = ['translation', 'music']
    store.selectedId = 'translation'
    await wrapper.get('.mod-row').trigger('contextmenu', { clientX: 100, clientY: 100 })
    const menu = wrapper.get('[data-testid="context-ai-recognize-types"]')
    expect(menu.text()).toContain('AI识别（2项）')
    await menu.trigger('click')
    await flushPromises()
    expect(invokeMock.mock.calls.filter(([method]) => method === 'recognize_mod_types'))
      .toEqual([['recognize_mod_types', 'translation'], ['recognize_mod_types', 'music']])
    expect(store.mods.map(item => item.mod_types))
      .toEqual([['language'], ['ui', 'custom:music'], ['unknown']])
    const rows = wrapper.findAll('.mod-row')
    expect(rows[0].text()).toContain('语言包')
    expect(rows[1].text()).toContain('UI')
    expect(rows[1].text()).toContain('音乐')
    expect(store.mods[0]).toMatchObject({ alias: 'player title', notes: 'player notes' })
    expect(store.toast.message).toContain('成功 2 项，失败 0 项')
    expect(store.busy).toBe('')
  })

  it('identifies a single right-clicked MOD without changing the other MODs', async () => {
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.get('.mod-row').trigger('contextmenu', { clientX: 100, clientY: 100 })
    await wrapper.get('[data-testid="context-ai-recognize-types"]').trigger('click')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('recognize_mod_types', 'translation')
    expect(store.mods[0].mod_types).toEqual(['language'])
    expect(store.mods[1].mod_types).toEqual(['unknown'])
    expect(store.toast.message).toContain('语言包')
  })

  it('deduplicates requests and continues after failure while retaining failed labels', async () => {
    invokeMock.mockResolvedValueOnce({ id: 'translation', mod_type: 'language', mod_types: ['language'] })
      .mockRejectedValueOnce(new Error('provider offline'))
      .mockResolvedValueOnce({ id: 'untouched', mod_type: 'ui', mod_types: ['ui', 'custom:music'] })
    const result = await store.recognizeModTypesMany(['translation', 'music', 'translation', 'untouched'])
    expect(result).toEqual({ succeeded: ['translation', 'untouched'], failed: ['music'] })
    expect(invokeMock.mock.calls).toEqual([
      ['recognize_mod_types', 'translation'], ['recognize_mod_types', 'music'], ['recognize_mod_types', 'untouched'],
    ])
    expect(store.mods[1].mod_types).toEqual(['unknown'])
    expect(store.toast.message).toContain('成功 2 项，失败 1 项')
    expect(store.toast.message).toContain('provider offline')
    expect(store.toast.type).toBe('warning')
  })

  it('discards stale results after a game switch and stops the remaining batch', async () => {
    let resolveRequest
    invokeMock.mockImplementation(() => new Promise(resolve => { resolveRequest = resolve }))
    const task = store.recognizeModTypesMany(['translation', 'music'])
    store.gameContextRevision += 1
    resolveRequest({ id: 'translation', mod_type: 'language', mod_types: ['language'] })
    await task
    expect(store.mods[0].mod_types).toEqual(['unknown'])
    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(store.busy).toBe('')
  })
})
