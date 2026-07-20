// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'

import {
  KEYBOARD_SHORTCUTS,
  executeKeyboardShortcut,
  formatShortcut,
  normalizeShortcut,
  resolveKeyboardShortcut,
} from '../keyboardShortcuts'

const mod = (id, workshopId = '') => ({ id, workshop_id: workshopId })

describe('keyboard shortcuts', () => {
  it('normalizes and formats modifier combinations', () => {
    expect(normalizeShortcut(' alt + shift + k ')).toBe('Alt+Shift+K')
    expect(formatShortcut('Ctrl+Alt+Shift+Enter')).toBe('Ctrl + Alt + Shift + Enter')
    expect(normalizeShortcut('Shift')).toBe('')
  })

  it('maps the requested Shift bindings and ignores unsafe input contexts', () => {
    expect(KEYBOARD_SHORTCUTS.map(item => item.id)).toEqual([
      'open-workshop',
      'open-rpfm',
      'toggle-active',
      'launch-game',
      'manual-type',
    ])
    expect(resolveKeyboardShortcut({ key: 'w', shiftKey: true })).toBe('open-workshop')
    expect(resolveKeyboardShortcut({ key: 'R', shiftKey: true })).toBe('open-rpfm')
    expect(resolveKeyboardShortcut({ key: 'e', shiftKey: true })).toBe('toggle-active')
    expect(resolveKeyboardShortcut({ key: 'Enter', shiftKey: true })).toBe('launch-game')
    expect(resolveKeyboardShortcut({ key: 'f', shiftKey: true })).toBe('manual-type')
    expect(resolveKeyboardShortcut({ key: 'w', shiftKey: true, ctrlKey: true })).toBe('')
    expect(resolveKeyboardShortcut(
      { key: 'k', ctrlKey: true, altKey: true },
      { shortcuts: { 'open-workshop': 'Ctrl+Alt+K' } },
    )).toBe('open-workshop')
    expect(resolveKeyboardShortcut({ key: 'w', shiftKey: true }, { enabled: false })).toBe('')

    const input = document.createElement('input')
    expect(resolveKeyboardShortcut({ key: 'w', shiftKey: true, target: input })).toBe('')
    expect(resolveKeyboardShortcut({ key: 'w', shiftKey: true }, { blocked: true })).toBe('')
  })

  it('uses the current selection for Workshop, RPFM and enable-state shortcuts', async () => {
    const first = mod('first', '123')
    const second = mod('second', '456')
    const byId = new Map([[first.id, first], [second.id, second]])
    const openWorkshop = vi.fn().mockResolvedValue()
    const openRpfm = vi.fn().mockResolvedValue()
    const enableMany = vi.fn()
    const disableMany = vi.fn()

    await expect(executeKeyboardShortcut('open-workshop', {
      selectedMod: first,
      selectedIds: ['first', 'second'],
      getMod: id => byId.get(id),
      openWorkshop,
    })).resolves.toEqual({ handled: true })
    expect(openWorkshop).toHaveBeenNthCalledWith(1, 'first')
    expect(openWorkshop).toHaveBeenNthCalledWith(2, 'second')

    await expect(executeKeyboardShortcut('open-rpfm', {
      selectedMod: first,
      selectedIds: ['first'],
      getMod: id => byId.get(id),
      openRpfm,
    })).resolves.toEqual({ handled: true })
    expect(openRpfm).toHaveBeenCalledWith('first')

    await expect(executeKeyboardShortcut('toggle-active', {
      selectedMod: first,
      selectedIds: ['first', 'second'],
      getMod: id => byId.get(id),
      activeIds: ['first'],
      enableMany,
      disableMany,
    })).resolves.toEqual({ handled: true })
    expect(disableMany).toHaveBeenCalledWith(['first', 'second'])
    expect(enableMany).not.toHaveBeenCalled()
  })

  it('executes manual type entry for the current selection', async () => {
    const manualType = vi.fn().mockResolvedValue()

    await expect(executeKeyboardShortcut('manual-type', {
      selectedMod: mod('first'),
      selectedIds: ['first'],
      getMod: id => mod(id),
      manualType,
    })).resolves.toEqual({ handled: true })
    expect(manualType).toHaveBeenCalledWith(['first'])
  })

  it('launches only when the existing launch button would be available and reports unavailable selections', async () => {
    const launch = vi.fn().mockResolvedValue()

    await expect(executeKeyboardShortcut('launch-game', {
      canLaunch: true,
      launch,
    })).resolves.toEqual({ handled: true })
    expect(launch).toHaveBeenCalledTimes(1)

    await expect(executeKeyboardShortcut('launch-game', {
      canLaunch: false,
      launch,
    })).resolves.toEqual({ handled: false, reason: 'launch-unavailable' })

    await expect(executeKeyboardShortcut('open-workshop', {
      selectedMod: mod('local'),
      selectedIds: ['local'],
      getMod: () => mod('local'),
      openWorkshop: vi.fn(),
    })).resolves.toEqual({ handled: false, reason: 'workshop-required' })

    await expect(executeKeyboardShortcut('open-rpfm', {
      selectedMod: mod('first'),
      selectedIds: ['first', 'second'],
      getMod: id => mod(id),
      openRpfm: vi.fn(),
    })).resolves.toEqual({ handled: false, reason: 'single-selection-required' })
  })
})
