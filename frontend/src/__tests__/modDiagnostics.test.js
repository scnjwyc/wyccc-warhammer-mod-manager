// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import ModDiagnosticsModal from '../components/ModDiagnosticsModal.vue'
import { useAppStore } from '../store'
import { applyInterfaceLanguage, localizeBackendMessage } from '../languages'

beforeEach(() => { setActivePinia(createPinia()); invokeMock.mockReset(); applyInterfaceLanguage('zh-CN') })

describe('diagnostic trial controls', () => {
  it('does not start a trial just by opening the panel', async () => {
    const wrapper = mount(ModDiagnosticsModal, { props: { open: true, enabledCount: 3 } })
    expect(wrapper.emitted('start')).toBeUndefined()
    await wrapper.get('input[value="maxload"]').setValue()
    await wrapper.get('[data-testid="diagnostics-start"]').trigger('click')
    expect(wrapper.emitted('start')).toEqual([['maxload']])
  })

  it('binds a user verdict to the visible session and round', async () => {
    const session = { id: 'session-1', status: 'running', running: true, round_number: 4, phase: 'preparing' }
    const wrapper = mount(ModDiagnosticsModal, { props: { open: true, session } })
    expect(wrapper.get('[data-testid="diagnostics-menu-ok"]').element.disabled).toBe(true)
    await wrapper.setProps({ session: { ...session, phase: 'confirm_menu' } })
    await wrapper.get('[data-testid="diagnostics-menu-ok"]').trigger('click')
    expect(wrapper.emitted('confirm-trial')).toEqual([[{ id: 'session-1', round: 4, verdict: 'ok' }]])
    await wrapper.get('.modal-backdrop').trigger('mousedown')
    expect(wrapper.emitted('close')).toBeUndefined()
    await wrapper.get('[data-testid="diagnostics-cancel"]').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('never offers to apply an unverified suspect or a cancelled run', async () => {
    const session = { id: 'one', status: 'multiple', running: false, suspect_ids: ['a'], mods: { a: { name: 'Example' } } }
    const wrapper = mount(ModDiagnosticsModal, { props: { open: true, session } })
    expect(wrapper.text()).toContain('Example')
    expect(wrapper.find('[data-testid="diagnostics-apply"]').exists()).toBe(false)
    await wrapper.setProps({ session: { ...session, status: 'isolated', can_apply: true } })
    await wrapper.get('[data-testid="diagnostics-apply"]').trigger('click')
    expect(wrapper.emitted('apply')).toHaveLength(1)
    await wrapper.setProps({ gameRunning: true })
    expect(wrapper.get('[data-testid="diagnostics-apply"]').element.disabled).toBe(true)
  })

  it('starts with current enabled MODs without disabling any of them', async () => {
    const store = useAppStore()
    store.activeIds = ['a', 'b']
    invokeMock.mockResolvedValue({ id: 'session', running: true })
    await store.startModDiagnostics('bisect')
    expect(invokeMock).toHaveBeenCalledWith('start_mod_diagnostics', ['a', 'b'], 'bisect')
    expect(store.activeIds).toEqual(['a', 'b'])
    expect(invokeMock.mock.calls.some(([method]) => method === 'update_playset')).toBe(false)
  })

  it('accepts the list and token already saved by the backend without a second write', async () => {
    const store = useAppStore()
    store.activeIds = ['a', 'b']
    store.mods = [{ id: 'a', pack_name: 'a.pack' }, { id: 'b', pack_name: 'b.pack' }]
    store.currentPlaysetId = 'default'
    store.orderToken = 'old-token'
    invokeMock.mockResolvedValue({ current_playset: { id: 'default', mod_ids: ['a'] },
      ordered_mod_ids: ['a'], order_token: 'new-token', backup: { id: 'backup-1' } })
    await store.applyDiagnosticsResult('verified-run')
    expect(store.activeIds).toEqual(['a'])
    expect(invokeMock).toHaveBeenCalledExactlyOnceWith('apply_diagnostics_result', 'verified-run', false, 'old-token')
    expect(store.orderToken).toBe('new-token')
    expect(store.dirty).toBe(false)
    expect(store.backups[0].id).toBe('backup-1')
  })

  it.each([
    { current_playset: { id: 'default', mod_ids: ['a'] }, order_token: 'new-token' },
    { ordered_mod_ids: ['a'] },
  ])('rejects an incomplete response without changing the active list: %j', async payload => {
    const store = useAppStore()
    store.activeIds = ['a', 'b']
    store.orderToken = 'old-token'
    invokeMock.mockResolvedValue(payload)
    await expect(store.applyDiagnosticsResult('verified-run')).rejects.toThrow('应用结果缺少完整加载清单')
    expect(store.activeIds).toEqual(['a', 'b'])
    expect(store.orderToken).toBe('old-token')
    expect(invokeMock).toHaveBeenCalledTimes(1)
  })

  it('keeps the current configuration when the backend save fails', async () => {
    const store = useAppStore()
    store.activeIds = ['a', 'b']
    store.orderToken = 'old-token'
    invokeMock.mockRejectedValue(new Error('disk full'))
    await expect(store.applyDiagnosticsResult('verified-run')).rejects.toThrow('disk full')
    expect(store.activeIds).toEqual(['a', 'b'])
    expect(store.orderToken).toBe('old-token')
    expect(invokeMock).toHaveBeenCalledTimes(1)
  })

  it('accepts an explicitly verified empty list', async () => {
    const store = useAppStore()
    store.activeIds = ['a']
    store.mods = [{ id: 'a', pack_name: 'a.pack' }]
    invokeMock.mockResolvedValue({ current_playset: { id: 'default', mod_ids: [] },
      ordered_mod_ids: [], order_token: 'empty-token' })
    await store.applyDiagnosticsResult('verified-run')
    expect(store.activeIds).toEqual([])
    expect(store.orderToken).toBe('empty-token')
    expect(invokeMock).toHaveBeenCalledTimes(1)
  })

  it.each(['confirm_exit', 'confirm_dump'])('enables manual verdicts in phase %s', async phase => {
    const wrapper = mount(ModDiagnosticsModal, { props: { open: true,
      session: { id: 'quick-exit', status: 'running', running: true, phase, round_number: 2 } } })
    expect(wrapper.get('[data-testid="diagnostics-menu-ok"]').element.disabled).toBe(false)
    expect(wrapper.get('[data-testid="diagnostics-trial-crash"]').element.disabled).toBe(false)
  })

  it('translates backend diagnostic errors in the selected language', () => {
    applyInterfaceLanguage('en-US')
    expect(localizeBackendMessage('diagnostics.staleTrial')).toBe('This trial has changed; check the latest progress')
    applyInterfaceLanguage('es-ES')
    expect(localizeBackendMessage('diagnostics.noVerifiedResult')).toBe('No hay un resultado verificado para aplicar')
  })
})
