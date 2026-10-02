import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))
import { useAppStore } from '../store'

const root = resolve(process.cwd(), '..')
const localPython = resolve(root, process.platform === 'win32'
  ? '.venv-build/Scripts/python.exe' : '.venv-build/bin/python')
const python = process.env.PYTHON || (existsSync(localPython) ? localPython : 'python')

describe('diagnostics apply across the backend/frontend boundary', () => {
  it.each([false, true])('uses the real saved response with restore=%s', async restore => {
    const args = ['-m', 'tests.diagnostics_bridge_fixture', ...(restore ? ['--restore'] : [])]
    const snapshot = JSON.parse(execFileSync(python, args, { cwd: root, encoding: 'utf8' }))
    const expected = restore ? ['a', 'b', 'c'] : ['a', 'c']
    setActivePinia(createPinia())
    const store = useAppStore()
    store.mods = ['a', 'b', 'c'].map(id => ({ id, pack_name: `${id}.pack` }))
    store.activeIds = ['a', 'b', 'c']
    store.currentPlaysetId = snapshot.payload.current_playset.id
    store.playsets = [{ id: store.currentPlaysetId, mod_ids: ['a', 'b', 'c'] }]
    invokeMock.mockResolvedValue(snapshot.payload)

    await store.applyDiagnosticsResult('verified-run', restore)

    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(store.activeIds).toEqual(expected)
    expect(snapshot.persisted_ids).toEqual(expected)
    expect(snapshot.disk_pack_names).toEqual(expected.map(id => `${id}.pack`))
    expect(store.orderToken).toBe(snapshot.disk_token)
    expect(store.dirty).toBe(false)
  })
})
