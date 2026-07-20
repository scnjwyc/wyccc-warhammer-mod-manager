const MODIFIER_ALIASES = Object.freeze({
  ctrl: 'Ctrl',
  control: 'Ctrl',
  alt: 'Alt',
  shift: 'Shift',
  meta: 'Meta',
  win: 'Meta',
  cmd: 'Meta',
  command: 'Meta',
})

const MODIFIER_ORDER = Object.freeze(['Ctrl', 'Alt', 'Shift', 'Meta'])
const KEY_ALIASES = Object.freeze({
  esc: 'Escape',
  escape: 'Escape',
  return: 'Enter',
  enter: 'Enter',
  space: 'Space',
  tab: 'Tab',
  backspace: 'Backspace',
  delete: 'Delete',
  del: 'Delete',
  insert: 'Insert',
  home: 'Home',
  end: 'End',
  pageup: 'PageUp',
  pagedown: 'PageDown',
  arrowup: 'ArrowUp',
  arrowdown: 'ArrowDown',
  arrowleft: 'ArrowLeft',
  arrowright: 'ArrowRight',
})

export const KEYBOARD_SHORTCUTS = Object.freeze([
  { id: 'open-workshop', defaultShortcut: 'Shift+W', keys: 'Shift + W', labelKey: 'shortcuts.openWorkshop' },
  { id: 'open-rpfm', defaultShortcut: 'Shift+R', keys: 'Shift + R', labelKey: 'shortcuts.openRpfm' },
  { id: 'toggle-active', defaultShortcut: 'Shift+E', keys: 'Shift + E', labelKey: 'shortcuts.toggleActive' },
  { id: 'launch-game', defaultShortcut: 'Shift+Enter', keys: 'Shift + Enter', labelKey: 'shortcuts.launchGame' },
  { id: 'manual-type', defaultShortcut: 'Shift+F', keys: 'Shift + F', labelKey: 'shortcuts.manualType' },
])

const shortcutMetadata = new Map(KEYBOARD_SHORTCUTS.map(shortcut => [shortcut.id, shortcut]))

const normalizeKey = value => {
  const token = String(value || '').trim()
  if (!token) return ''
  const folded = token.toLocaleLowerCase()
  if (MODIFIER_ALIASES[folded]) return ''
  if (KEY_ALIASES[folded]) return KEY_ALIASES[folded]
  return token.length === 1 ? token.toUpperCase() : `${token[0].toUpperCase()}${token.slice(1).toLocaleLowerCase()}`
}

export const normalizeShortcut = value => {
  if (typeof value !== 'string' || !value.trim()) return ''
  const modifiers = new Set()
  let base = ''
  for (const rawPart of value.split('+')) {
    const part = rawPart.trim()
    if (!part) return ''
    const modifier = MODIFIER_ALIASES[part.toLocaleLowerCase()]
    if (modifier) {
      if (modifiers.has(modifier)) return ''
      modifiers.add(modifier)
      continue
    }
    if (base) return ''
    base = normalizeKey(part)
    if (!base) return ''
  }
  if (!base) return ''
  return [...MODIFIER_ORDER.filter(modifier => modifiers.has(modifier)), base].join('+')
}

export const formatShortcut = value => {
  const normalized = normalizeShortcut(value)
  return normalized ? normalized.split('+').join(' + ') : ''
}

export const normalizeShortcutMap = shortcuts => Object.fromEntries(
  KEYBOARD_SHORTCUTS.map(({ id, defaultShortcut }) => {
    const candidate = shortcuts && Object.prototype.hasOwnProperty.call(shortcuts, id)
      ? normalizeShortcut(shortcuts[id])
      : ''
    return [id, candidate || defaultShortcut]
  }),
)

export const shortcutForAction = (action, shortcuts) => formatShortcut(
  normalizeShortcutMap(shortcuts)[action] || shortcutMetadata.get(action)?.defaultShortcut || '',
)

export const shortcutFromKeyboardEvent = event => {
  if (!event) return ''
  const modifiers = [
    event.ctrlKey && 'Ctrl',
    event.altKey && 'Alt',
    event.shiftKey && 'Shift',
    event.metaKey && 'Meta',
  ].filter(Boolean)
  const base = normalizeKey(event.key)
  if (!base) return ''
  return normalizeShortcut([...modifiers, base].join('+'))
}

const isEditableTarget = target => {
  const tagName = String(target?.tagName || '').toLowerCase()
  if (['input', 'textarea', 'select', 'button', 'a'].includes(tagName)) return true
  if (target?.isContentEditable) return true
  return typeof target?.closest === 'function'
    && Boolean(target.closest('[contenteditable="true"], [role="textbox"]'))
}

const selectedShortcutIds = ({ selectedMod, selectedIds, getMod }) => {
  const selectedId = String(selectedMod?.id || '')
  if (!selectedId) return []
  const requestedIds = Array.isArray(selectedIds)
    && selectedIds.map(id => String(id)).includes(selectedId)
    ? selectedIds
    : [selectedId]
  return [...new Set(requestedIds.map(id => String(id || '')).filter(Boolean))]
    .filter(id => typeof getMod === 'function' && getMod(id))
}

export const resolveKeyboardShortcut = (event, {
  enabled = true,
  blocked = false,
  shortcuts,
} = {}) => {
  if (
    !enabled
    || blocked
    || event?.defaultPrevented
    || event?.isComposing
    || event?.repeat
    || isEditableTarget(event?.target)
  ) return ''
  const pressed = shortcutFromKeyboardEvent(event)
  if (!pressed) return ''
  const bindings = normalizeShortcutMap(shortcuts)
  return KEYBOARD_SHORTCUTS.find(({ id }) => bindings[id] === pressed)?.id || ''
}

export const executeKeyboardShortcut = async (action, {
  selectedMod = null,
  selectedIds = [],
  getMod,
  activeIds = [],
  canLaunch = false,
  openWorkshop,
  openRpfm,
  enableMany,
  disableMany,
  manualType,
  launch,
} = {}) => {
  if (action === 'launch-game') {
    if (!canLaunch) return { handled: false, reason: 'launch-unavailable' }
    await launch()
    return { handled: true }
  }

  const selection = selectedShortcutIds({ selectedMod, selectedIds, getMod })
  if (!selection.length) return { handled: false, reason: 'selection-required' }

  if (action === 'open-workshop') {
    const workshopIds = selection.filter(id => getMod(id)?.workshop_id)
    if (!workshopIds.length) return { handled: false, reason: 'workshop-required' }
    for (const modId of workshopIds) await openWorkshop(modId)
    return { handled: true }
  }

  if (action === 'open-rpfm') {
    if (selection.length !== 1) return { handled: false, reason: 'single-selection-required' }
    await openRpfm(selection[0])
    return { handled: true }
  }

  if (action === 'manual-type') {
    if (typeof manualType !== 'function') return { handled: false, reason: 'unknown-shortcut' }
    await manualType(selection)
    return { handled: true }
  }

  if (action === 'toggle-active') {
    if (activeIds.includes(selectedMod.id)) disableMany(selection)
    else enableMany(selection)
    return { handled: true }
  }

  return { handled: false, reason: 'unknown-shortcut' }
}
