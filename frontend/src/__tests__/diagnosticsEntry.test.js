// @vitest-environment jsdom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import App from '../App.vue'
import SettingsModal from '../components/SettingsModal.vue'
import ModDiagnosticsModal from '../components/ModDiagnosticsModal.vue'
import { useAppStore } from '../store'

describe('manual diagnostics entry', () => {
  let wrapper, store, pinia
  beforeEach(() => {
    vi.useFakeTimers()
    pinia = createPinia()
    setActivePinia(pinia)
    store = useAppStore()
    store.settings = { selected_game: 'warhammer3', language: 'zh-CN' }
    store.pathHealth = { game_ready: true }
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    vi.spyOn(store, 'refreshRuntime').mockResolvedValue()
    invokeMock.mockReset()
    invokeMock.mockImplementation(async method => {
      if (method === 'get_mod_diagnostics') return { running: false, status: 'idle' }
      if (method === 'get_diagnostics_history') return []
      return {}
    })
  })
  afterEach(() => {
    wrapper?.unmount()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })
  const openApp = async () => {
    wrapper = shallowMount(App, { global: { plugins: [pinia], stubs: { SettingsModal: false } } })
    await flushPromises()
  }

  it('opens from Settings > Features and removes the footer entry', async () => {
    await openApp()
    expect(wrapper.get('.footer-left').find('[data-testid="mod-diagnostics-button"]').exists()).toBe(false)
    await wrapper.findAll('.header-actions button').find(button => button.text() === '设置').trigger('click')
    const settings = wrapper.getComponent(SettingsModal)
    await settings.get('[data-testid="settings-tab-features"]').trigger('click')
    const entry = settings.get('[data-testid="settings-page-features"] [data-testid="mod-diagnostics-button"]')
    expect(entry.isVisible()).toBe(true)
    await entry.trigger('click')
    await flushPromises()
    expect(settings.props('open')).toBe(false)
    expect(wrapper.getComponent(ModDiagnosticsModal).props('open')).toBe(true)
  })

  it('never opens on bootstrap or background polling even when a diagnostic session is running', async () => {
    invokeMock.mockImplementation(async method => method === 'get_mod_diagnostics'
      ? { running: true, status: 'running', phase: 'confirm_exit' } : {})
    await openApp()
    expect(wrapper.getComponent(ModDiagnosticsModal).props('open')).toBe(false)
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.getComponent(ModDiagnosticsModal).props('open')).toBe(false)
  })

  it('keeps the panel closed when the game exits with a new crash diagnosis', async () => {
    invokeMock.mockImplementation(async method => {
      if (method === 'get_mod_diagnostics') return { running: false }
      if (method === 'get_crash_diagnosis') return { new_crash: true, show_prompt: true }
      if (method === 'get_diagnostics_history') return []
      return {}
    })
    await openApp()
    store.runtime.running = true
    await flushPromises()
    store.runtime.running = false
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('get_crash_diagnosis')
    expect(wrapper.getComponent(ModDiagnosticsModal).props('open')).toBe(false)
  })
})
