<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { localizedModTypeName, localizedPlaysetName, t } from './languages'
import { executeKeyboardShortcut, isUndoShortcut, resolveKeyboardShortcut } from './keyboardShortcuts'
import { useAppStore } from './store'
import { GAME_OPTIONS } from './games'
import ConfirmationModal from './components/ConfirmationModal.vue'
import FolderNameModal from './components/FolderNameModal.vue'
import DeleteModsModal from './components/DeleteModsModal.vue'
import CompatibilityPatchModal from './components/CompatibilityPatchModal.vue'
import GameDataModificationModal from './components/GameDataModificationModal.vue'
import UnitDataModificationModal from './components/UnitDataModificationModal.vue'
import UnitEncyclopediaModal from './components/UnitEncyclopediaModal.vue'
import ModContextMenu from './components/ModContextMenu.vue'
import ModDetails from './components/ModDetails.vue'
import ModDiagnosticsModal from './components/ModDiagnosticsModal.vue'
import SchemaUpdateModal from './components/SchemaUpdateModal.vue'
import ModList from './components/ModList.vue'
import OfficialProfileImportModal from './components/OfficialProfileImportModal.vue'
import SaveGamesModal from './components/SaveGamesModal.vue'
import SaveModsComparisonModal from './components/SaveModsComparisonModal.vue'
import SettingsModal from './components/SettingsModal.vue'
import ShareModal from './components/ShareModal.vue'
import ThemedSelect from './components/ThemedSelect.vue'
import TypeManagerModal from './components/TypeManagerModal.vue'
import UpdateModal from './components/UpdateModal.vue'
import WarningModal from './components/WarningModal.vue'
import WorkshopPublishModal from './components/WorkshopPublishModal.vue'

const store = useAppStore()
const showGameDataModification = ref(false)
const showUnitDataModification = ref(false)
const showUnitEncyclopedia = ref(false)
const unitEncyclopediaRevision = ref(0)
const openingUnitDataModification = ref(false)
const showCompatibilityPatch = ref(false)
const showDiagnostics = ref(false)
const diagnosticsBusy = ref(false)
const diagnosticSession = ref({ status: 'idle', running: false })
const crashDiagnosis = ref({})
const diagnosticHistory = ref([])
let diagnosticsPolling = false
let diagnosticsViewRevision = 0
const showSettings = ref(false)
const showShare = ref(false)
const showTypeManager = ref(false)
const showWarnings = ref(false)
const showSaveGames = ref(false)
const showSaveModsComparison = ref(false)
const saveModsComparison = ref(null)
const showOfficialProfileImport = ref(false)
const officialProfilePreview = ref(null)
const showDeleteMods = ref(false)
const deleteModsPreview = ref(null)
const schemaUpdate = reactive({ open: false, pending: false, report: null, error: '' })
const updateDialog = reactive({ open: false, mode: 'update' })
const shareValue = ref('')
const unitDataSearch = ref('')
const unitDataUnitKey = ref('')
const unitDataSnapshotToken = ref('')
const contextMenu = reactive({ open: false, x: 0, y: 0, modId: '' })
const workshopPublish = reactive({ open: false, mode: 'upload', modId: '', queue: [] })
const confirmationDialog = reactive({ open: false, message: '', confirmLabel: '', danger: false })
const folderDialog = reactive({ open: false, rename: false, folderId: '', name: '', modIds: [], error: '' })
const modDragSource = ref(null)
let runtimeTimer = 0
let updateTimer = 0
let confirmationResolver = null

const contextMod = computed(() => store.modMap.get(contextMenu.modId) || null)
const contextModActive = computed(() => !!contextMod.value && store.activeIds.includes(contextMod.value.id))
const activeGame = computed(() => store.settings.selected_game || 'warhammer3')
const supportsWh3Tools = computed(() => activeGame.value === 'warhammer3')
const supportsUnitDataTools = computed(() => (
  activeGame.value === 'warhammer3' || activeGame.value === 'three_kingdoms'
))
const activeGameDefinition = computed(() => (
  GAME_OPTIONS.find(game => game.id === activeGame.value) || GAME_OPTIONS[0]
))
const supportsPackActions = computed(() => activeGameDefinition.value.modFormat === 'pack')
const supportsSaveGames = computed(() => activeGameDefinition.value.supportsSaveGames)
const unitSizeFeature = computed(() => store.gameDataFeatures.unit_size)
const friendlyFireFeature = computed(() => store.gameDataFeatures.friendly_fire)
const unitCapFeature = computed(() => store.gameDataFeatures.unit_cap)
const unitDataModIds = computed(() => (
  store.unitDataFeatureSubscribed ? store.unitDataModIds : []
))
const REQUIRED_NANU_ROR_PACKS = [
  {
    pack: '!!_nanu_dynamic_rors.pack',
    name: "Nanu's Dynamic Regiments of Renown",
    requirement: 'enabled',
  },
  {
    pack: 'wyccc_nanu_rors_patch.pack',
    name: "Nanu's Dynamic RORs Ultimate Compatibility Patch",
    requirement: 'installed',
  },
]
const nanuRorPackRequirement = computed(() => {
  const installedByPack = new Map()
  for (const mod of store.mods) {
    const pack = String(mod?.pack_name || '')
    if (pack && !installedByPack.has(pack.toLocaleLowerCase())) {
      installedByPack.set(pack.toLocaleLowerCase(), mod)
    }
  }
  const activePacks = new Set()
  for (const id of store.activeIds) {
    const mod = store.modMap.get(id)
    const pack = String(mod?.pack_name || '')
    if (pack) {
      activePacks.add(pack.toLocaleLowerCase())
    }
  }
  const missing = REQUIRED_NANU_ROR_PACKS
    .filter(required => {
      const key = required.pack.toLocaleLowerCase()
      const installed = installedByPack.has(key)
      if (required.requirement === 'installed') return !installed
      return !installed || !activePacks.has(key)
    })
    .map(required => {
      const mod = installedByPack.get(required.pack.toLocaleLowerCase())
      return mod?.effective_name || mod?.display_name || required.name
    })
  return { allEnabled: missing.length === 0, missing }
})
const variantSelectorPackRequirement = computed(() => {
  const basePack = String(
    store.variantSelectorFeature?.base_pack_name || '!marthvariantselector.pack',
  )
  const baseEnabled = store.mods.some(mod => (
    (mod.provides_variant_selector
      || String(mod.workshop_id || '') === '2888171970'
      || String(mod.pack_name || '').toLocaleLowerCase() === basePack.toLocaleLowerCase())
    && (store.activeIds.includes(mod.id) || mod.pack_type === 'movie')
  ))
  const missing = []
  if (!store.variantSelectorFeatureSubscribed) {
    missing.push(store.variantSelectorFeature?.title || 'Dynamic Variant Selector Patch')
  }
  if (!baseEnabled) {
    missing.push('Variant Selector')
  }
  return { allEnabled: missing.length === 0, missing }
})
const workshopPublishMod = computed(() => store.modMap.get(workshopPublish.modId) || null)
const inactiveSearchFocusId = computed(() => (
  store.inactiveSearchHighlightActive
    ? store.inactiveSearchMatchIds[0] || ''
    : ''
))
const activeSearchFocusId = computed(() => (
  store.activeSearchHighlightActive
    ? store.activeSearchMatchIds[0] || ''
    : ''
))
const playsetOptions = computed(() => store.playsets.map(playset => ({
  value: playset.id,
  label: localizedPlaysetName(playset),
})))
const statusDisplay = computed(() => {
  if (store.busy) return { text: store.busy, kind: 'busy', spinning: true }
  if (store.workshopRefreshing) return { text: t('status.refreshingWorkshop'), kind: 'refresh', spinning: true }
  if (store.liveModRefreshing) return { text: t('status.refreshingModList'), kind: 'refresh', spinning: true }
  if (store.orderSaving) return { text: t('status.savingOrder'), kind: 'saving', spinning: true }
  if (store.orderSaveError || store.dirty) return { text: t('status.saveFailed'), kind: 'error', spinning: false }
  if (store.runtime.running) return { text: t('status.gameRunning'), kind: 'running', spinning: false }
  return { text: t('status.ready'), kind: 'ready', spinning: false }
})

const persistentWarningLabel = code => ({
  outdated_mod: t('app.warningOutdated'),
  workshop_update_available: t('app.warningWorkshopUpdate'),
  missing_dependency: t('app.warningMissingDependency'),
}[code] || t('app.warningOutdated'))

const requestConfirmation = ({ message, confirmLabel = '', danger = false }) => new Promise(resolve => {
  confirmationResolver?.(false)
  confirmationResolver = resolve
  confirmationDialog.message = message
  confirmationDialog.confirmLabel = confirmLabel
  confirmationDialog.danger = danger
  confirmationDialog.open = true
})

const completeConfirmation = confirmed => {
  const resolve = confirmationResolver
  confirmationResolver = null
  confirmationDialog.open = false
  if (resolve) resolve(confirmed)
}

watch(supportsWh3Tools, supported => {
  if (supported) return
  showUnitEncyclopedia.value = false
  showGameDataModification.value = false
  showCompatibilityPatch.value = false
  showOfficialProfileImport.value = false
  officialProfilePreview.value = null
})

watch(supportsUnitDataTools, supported => {
  if (!supported) showUnitDataModification.value = false
})

watch(supportsSaveGames, supported => {
  if (supported) return
  showSaveGames.value = false
  showSaveModsComparison.value = false
  saveModsComparison.value = null
})

const initialize = async () => {
  try {
    const bootstrap = await store.bootstrap()
    void refreshDiagnostics(false)
    if (!store.pathHealth.game_ready) showSettings.value = true
    if (bootstrap.show_changelog) {
      updateDialog.mode = 'changelog'
      updateDialog.open = true
    } else if (bootstrap.auto_update_due) {
      updateTimer = window.setTimeout(async () => {
        const info = await store.checkForUpdates(false)
        if (info?.has_update) {
          updateDialog.mode = 'update'
          updateDialog.open = true
        }
      }, 1500)
    }
  } catch {
    showSettings.value = true
  }
}

const saveSettings = async changes => {
  await store.saveSettings(changes)
  if (!store.pathHealth.game_ready) return
  showSettings.value = false
  await store.scan(false)
  if (store.settings.fetch_workshop_metadata) void store.refreshWorkshopInBackground()
}

const saveGameDataSettings = async changes => {
  await store.saveGameDataSettings(changes)
  showGameDataModification.value = false
}

const openGameDataModification = () => {
  if (!supportsWh3Tools.value) return
  showGameDataModification.value = true
  void store.refreshGameDataFeatures().catch(() => {})
}

const openUnitDataModification = async (mod = null, targetUnitKey = '', snapshotToken = '') => {
  if (!supportsUnitDataTools.value || openingUnitDataModification.value) return
  if (targetUnitKey && (store.busy || store.orderSaving || store.runtime.running)) return
  const requestGame = activeGame.value
  openingUnitDataModification.value = true
  try {
    await store.refreshUnitDataFeature()
    if (activeGame.value !== requestGame || (targetUnitKey && !showUnitEncyclopedia.value)) return
    if (store.unitDataFeature?.required !== false && !store.unitDataFeatureSubscribed) {
      await requestConfirmation({
        message: t('gameData.requiredModNotSubscribed', {
          mod: store.unitDataFeature?.title || 'Dynamic Units Modify',
        }),
      })
      return
    }
    unitDataSearch.value = mod
      ? (mod.effective_name || mod.display_name || mod.pack_name || '')
      : ''
    unitDataUnitKey.value = targetUnitKey
    unitDataSnapshotToken.value = snapshotToken
    showUnitDataModification.value = true
  } catch (error) {
    store.notify(error?.message || String(error), 'error')
  } finally {
    openingUnitDataModification.value = false
  }
}

const saveUnitData = async edits => {
  await store.saveUnitData(edits)
  if (showUnitEncyclopedia.value) unitEncyclopediaRevision.value += 1
  showUnitDataModification.value = false
}

const openCompatibilityPatch = async () => {
  if (!supportsWh3Tools.value) return
  await store.refreshVariantSelectorFeature().catch(() => {})
  showCompatibilityPatch.value = true
}

const saveCompatibilityPatch = async changes => {
  await store.saveCompatibilityPatchSettings(changes)
  showCompatibilityPatch.value = false
}

const detectPaths = async gameId => {
  await store.detectPaths(gameId)
  if (store.pathHealth.game_ready) {
    await store.scan(false)
    if (store.settings.fetch_workshop_metadata) void store.refreshWorkshopInBackground()
    showSettings.value = false
  }
}

const checkForUpdates = async () => {
  try {
    const info = await store.checkForUpdates(true)
    if (!info?.has_update) return
    showSettings.value = false
    updateDialog.mode = 'update'
    updateDialog.open = true
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const openChangelog = async () => {
  showSettings.value = false
  try {
    await store.loadChangelog()
  } catch (error) {
    store.notify(error.message || String(error), 'error')
  }
  updateDialog.mode = 'changelog'
  updateDialog.open = true
}

const closeUpdateDialog = async () => {
  if (store.busy) return
  const acknowledge = updateDialog.mode === 'changelog'
  updateDialog.open = false
  if (acknowledge) {
    try { await store.acknowledgeChangelog() } catch { /* shown again next launch */ }
  }
}

const downloadUpdate = async () => {
  try { await store.downloadUpdate() } catch { /* shared toast */ }
}

const installUpdate = async () => {
  try { await store.installUpdate() } catch { /* shared toast */ }
}

const ignoreUpdate = async () => {
  try {
    await store.ignoreUpdate()
    updateDialog.open = false
  } catch (error) {
    store.notify(error.message || String(error), 'error')
  }
}

const createPlayset = async () => {
  const name = window.prompt(t('app.promptNewPlayset'))
  if (!name?.trim()) return
  try { await store.createPlayset(name) } catch { /* shared toast */ }
}

const renamePlayset = async () => {
  if (!store.currentPlayset || store.currentPlayset.is_default) return
  const name = window.prompt(t('app.promptRenamePlayset'), store.currentPlayset.name)
  if (!name?.trim() || name.trim() === store.currentPlayset.name) return
  try { await store.renameCurrentPlayset(name) } catch { /* shared toast */ }
}

const deletePlayset = async () => {
  if (!store.currentPlayset || store.currentPlayset.is_default) return
  const confirmed = await requestConfirmation({
    message: t('app.confirmDeletePlayset', {
      name: store.currentPlayset.name,
      defaultName: t('common.default'),
    }),
    confirmLabel: t('common.delete'),
    danger: true,
  })
  if (!confirmed) return
  try { await store.deleteCurrentPlayset() } catch { /* shared toast */ }
}

const toggleCurrentPlaysetHiddenMods = async () => {
  try {
    await store.setCurrentPlaysetShowHiddenMods(!store.showHidden)
  } catch { /* shared toast */ }
}

const choosePlayset = async playsetId => {
  try { await store.switchPlayset(playsetId) } catch { /* shared toast */ }
}

const openShare = async () => {
  showShare.value = true
  shareValue.value = ''
}

const exportShare = async () => {
  const data = await store.exportShare()
  shareValue.value = data.share_code
}

const importShare = async value => {
  try {
    const preview = await store.previewShareImport(value)
    const unsubscribed = preview.unsubscribed || []
    if (unsubscribed.length) {
      const visibleItems = unsubscribed.slice(0, 20).map(item => {
        const name = item.title || item.pack_name || t('app.workshopItem', { id: item.workshop_id })
        return t('app.subscriptionItem', { name, id: item.workshop_id })
      })
      if (unsubscribed.length > visibleItems.length) {
        visibleItems.push(t('app.moreUnsubscribed', { count: unsubscribed.length - visibleItems.length }))
      }
      const confirmed = await requestConfirmation({
        message: t('app.confirmSubscribe', { items: visibleItems.join('\n') }),
      })
      if (!confirmed) return
      await store.subscribeWorkshopItems(unsubscribed.map(item => item.workshop_id))
    }
    await store.importShare(value)
    if (unsubscribed.length) {
      store.notify(
        t('app.subscribedRescan', { count: unsubscribed.length }),
      )
    }
    showShare.value = false
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const openModContextMenu = payload => {
  const requestedSelection = store.selectedIds.includes(payload.mod.id)
    ? [...store.selectedIds]
    : [payload.mod.id]
  contextMenu.open = true
  contextMenu.x = payload.x
  contextMenu.y = payload.y
  contextMenu.modId = payload.mod.id
  void store.refreshWorkshopUpdateEligibility(requestedSelection)
  void store.selectMod({ id: payload.mod.id, preserveSelection: true })
}

const importWorkshopCollection = async value => {
  try {
    await store.importWorkshopCollection(value)
    showShare.value = false
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const selectedActionIds = modId => (
  store.selectedIds.includes(modId) ? store.selectedIds : [modId]
)

const contextSelectionCount = computed(() => (
  contextMod.value ? selectedActionIds(contextMod.value.id).length : 1
))
const contextSelectionIds = computed(() => (
  contextMod.value ? selectedActionIds(contextMod.value.id) : []
))

const enableSelected = modId => store.enableMany(selectedActionIds(modId))
const disableSelected = modId => store.disableMany(selectedActionIds(modId))
const toggleSingleMod = modId => (
  store.activeIds.includes(modId)
    ? store.disableMany([modId])
    : store.enableMany([modId])
)
const handleListDrop = payload => store.handleModDrop(payload)
const startModDrag = payload => { modDragSource.value = payload }
const endModDrag = () => { modDragSource.value = null }
const toggleSearchHighlight = async listName => {
  try {
    if (listName === 'active') {
      await store.setActiveSearchHighlightMode(!store.activeSearchHighlightMode)
    } else {
      await store.setInactiveSearchHighlightMode(!store.inactiveSearchHighlightMode)
    }
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const shortcutsBlocked = () => (
  showGameDataModification.value
  || showDiagnostics.value
  || showUnitDataModification.value
  || showUnitEncyclopedia.value
  || showSettings.value
  || showShare.value
  || showTypeManager.value
  || showWarnings.value
  || showSaveGames.value
  || showSaveModsComparison.value
  || showOfficialProfileImport.value
  || showDeleteMods.value
  || schemaUpdate.open
  || updateDialog.open
  || contextMenu.open
  || confirmationDialog.open
  || folderDialog.open
  || workshopPublish.open
)

const notifyShortcutOutcome = outcome => {
  const messageKey = {
    'selection-required': 'app.shortcutSelectMod',
    'workshop-required': 'app.shortcutWorkshopUnavailable',
    'single-selection-required': 'app.rpfmBatchBlocked',
  }[outcome.reason]
  if (messageKey) store.notify(t(messageKey), 'warning')
}

const handleGlobalShortcut = event => {
  if (isUndoShortcut(event)) {
    if (shortcutsBlocked() || store.busy || !store.canUndoListChange) return
    event.preventDefault()
    void store.undoListChange().catch(() => {
      // Store actions surface failures through the shared toast.
    })
    return
  }
  const action = resolveKeyboardShortcut(event, {
    enabled: Boolean(store.settings.keyboard_shortcuts_enabled),
    blocked: shortcutsBlocked(),
    shortcuts: store.settings.keyboard_shortcuts,
  })
  if (!action || store.busy) return
  event.preventDefault()
  void executeKeyboardShortcut(action, {
    selectedMod: store.selectedMod,
    selectedIds: store.selectedIds,
    getMod: modId => store.modMap.get(modId),
    activeIds: store.activeIds,
    canLaunch: !store.busy && store.pathHealth.game_ready && !store.runtime.running,
    openWorkshop: modId => store.openWorkshop(modId),
    openRpfm: modId => store.openModInRpfm(modId),
    enableMany: modIds => store.enableMany(modIds),
    disableMany: modIds => store.disableMany(modIds),
    manualType: modIds => enterManualModType(modIds, store.modMap.get(modIds[0]) || null),
    launch: () => store.launch(),
  }).then(notifyShortcutOutcome).catch(() => {
    // Store actions surface failures through the shared toast.
  })
}

const closeModContextMenu = () => {
  contextMenu.open = false
}

const toggleModFolder = async (folderId, listName) => {
  try { await store.toggleModFolder(folderId, listName) } catch {
    // Store actions surface failures through the shared toast.
  }
}
const renameModFolder = folder => {
  Object.assign(folderDialog, { open: true, rename: true, folderId: folder.id, name: folder.name, modIds: [], error: '' })
}
const submitModFolderName = async name => {
  folderDialog.error = ''
  try {
    const result = folderDialog.rename
      ? await store.renameModFolder(folderDialog.folderId, name)
      : await store.createModFolder(name, folderDialog.modIds)
    if (result) folderDialog.open = false
  } catch (error) {
    folderDialog.error = error.message || String(error)
  }
}
const deleteModFolder = async folder => {
  if (!await requestConfirmation({ message: t('folders.deleteConfirm', { name: folder.name }), confirmLabel: t('folders.delete') })) return
  try { await store.deleteModFolder(folder.id) } catch {
    // Store actions surface failures through the shared toast.
  }
}

const handleContextAction = async ({ action, value, mod }) => {
  if (!mod) return
  const actionIds = [...selectedActionIds(mod.id)]
  try {
    if (action === 'create-folder') {
      Object.assign(folderDialog, { open: true, rename: false, folderId: '', name: '', modIds: actionIds, error: '' })
    } else if (action === 'add-to-folder') {
      await store.assignModFolder(actionIds, value)
    } else if (action === 'remove-from-folder') {
      await store.assignModFolder(actionIds)
    } else if (action === 'toggle-active') {
      if (store.activeIds.includes(mod.id)) disableSelected(mod.id)
      else enableSelected(mod.id)
    } else if (action === 'toggle-type') {
      const contextTypes = new Set(mod.mod_types?.length ? mod.mod_types : [mod.mod_type || 'unknown'])
      const shouldHaveType = value === 'unknown' || !contextTypes.has(value)
      for (const modId of actionIds) {
        const target = store.modMap.get(modId)
        if (!target) continue
        const targetTypes = new Set(
          target.mod_types?.length ? target.mod_types : [target.mod_type || 'unknown'],
        )
        if (value === 'unknown' || targetTypes.has(value) !== shouldHaveType) {
          await store.toggleModType(modId, value)
        }
      }
    } else if (action === 'manage-types') {
      showTypeManager.value = true
    } else if (action === 'manual-type') {
      await enterManualModType(actionIds, mod)
    } else if (action === 'move-specific') {
      const current = store.activeIds.indexOf(mod.id) + 1
      const raw = window.prompt(t('app.promptLoadOrder', { count: store.activeIds.length }), String(current))
      if (raw === null) return
      const position = Number(raw)
      if (!Number.isInteger(position) || position < 1 || position > store.activeIds.length) {
        store.notify(t('app.invalidLoadOrder', { count: store.activeIds.length }), 'warning')
        return
      }
      store.moveManyToPosition(actionIds, position)
    } else if (action === 'move-top') {
      store.moveManyToPosition(actionIds, 1)
    } else if (action === 'move-bottom') {
      store.moveManyToPosition(actionIds, store.activeIds.length)
    } else if (action === 'open-workshop-browser') {
      for (const modId of actionIds) {
        if (store.modMap.get(modId)?.workshop_id) await store.openWorkshop(modId)
      }
    } else if (action === 'open-workshop-client') {
      for (const modId of actionIds) {
        if (store.modMap.get(modId)?.workshop_id) await store.openWorkshopClient(modId)
      }
    } else if (action === 'unsubscribe') {
      const targets = actionIds.filter(modId => store.modMap.get(modId)?.workshop_id)
      const subject = targets.length > 1
        ? t('app.selectedModsSubject', { count: targets.length })
        : t('app.singleModSubject', { name: mod.effective_name })
      const confirmed = await requestConfirmation({
        message: t('app.confirmUnsubscribe', { subject }),
        confirmLabel: t('context.unsubscribe'),
        danger: true,
      })
      if (!confirmed) return
      await store.unsubscribeWorkshopMany(targets)
    } else if (action === 'force-update') {
      for (const modId of actionIds) {
        if (store.modMap.get(modId)?.workshop_id) await store.forceUpdateWorkshop(modId)
      }
    } else if (action === 'publish-upload' || action === 'publish-update') {
      const mode = action === 'publish-update' ? 'update' : 'upload'
      if (
        mode === 'update'
        && actionIds.some(modId => !store.workshopUpdateEligibility.has(modId))
      ) return
      const targets = actionIds.filter(modId => {
        const target = store.modMap.get(modId)
        const sources = new Set(target?.sources?.length ? target.sources : [target?.source])
        if (!target) return false
        return mode === 'update'
          ? !!target.workshop_id
          : sources.has('data') && !target.workshop_id
      })
      if (!targets.length) return
      workshopPublish.open = true
      workshopPublish.mode = mode
      workshopPublish.queue = targets
      workshopPublish.modId = targets[0]
    } else if (action === 'copy-path') {
      await store.copyModPaths(actionIds)
    } else if (action === 'delete-file') {
      deleteModsPreview.value = await store.previewDeleteModFiles(actionIds)
      showDeleteMods.value = true
    } else if (action === 'open-folder') {
      for (const modId of actionIds) await store.openModFolder(modId)
    } else if (action === 'open-rpfm') {
      if (actionIds.length > 1) {
        store.notify(t('app.rpfmBatchBlocked'), 'warning')
        return
      }
      await store.openModInRpfm(mod.id)
    } else if (action === 'update-table-schemas') {
      if (store.runtime.running || store.busy) return
      Object.assign(schemaUpdate, { open: true, pending: true, report: null, error: '' })
      try {
        schemaUpdate.report = await store.updateModTableSchemas(actionIds)
      } catch (error) {
        schemaUpdate.error = error.message || String(error)
      } finally {
        schemaUpdate.pending = false
      }
    } else if (action === 'toggle-hidden') {
      const hidden = !mod.hidden
      for (const modId of actionIds) {
        if (store.modMap.get(modId)?.hidden !== hidden) await store.setModHidden(modId, hidden)
      }
    } else if (action === 'toggle-warning-ignore') {
      const ignored = new Set(mod.ignored_warning_codes || [])
      const shouldIgnore = !ignored.has(value)
      for (const modId of actionIds) {
        const targetIgnored = new Set(store.modMap.get(modId)?.ignored_warning_codes || [])
        if (targetIgnored.has(value) !== shouldIgnore) {
          await store.setModWarningIgnored(modId, value, shouldIgnore)
        }
      }
      const warningLabel = persistentWarningLabel(value)
      store.notify(
        t('app.warningBatchChanged', {
          action: shouldIgnore ? t('app.actionIgnored') : t('app.actionRestored'),
          count: actionIds.length,
          warning: warningLabel,
        }),
      )
    } else if (action === 'copy-to-data') {
      const targets = actionIds
        .map(modId => store.modMap.get(modId))
        .filter(Boolean)
        .map(target => ({ id: target.id, packName: String(target.pack_name || '') }))
      for (const target of targets) {
        const current = store.modMap.get(target.id)
          || store.mods.find(
            item => String(item.pack_name || '').toLocaleLowerCase() === target.packName.toLocaleLowerCase(),
          )
        const sources = new Set(current?.sources?.length ? current.sources : [current?.source])
        if (current && !sources.has('data')) await store.copyModToData(current.id)
      }
    } else if (action === 'generate-user-data') {
      await store.generateModUserDataMany(actionIds)
    }
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const closeWorkshopPublish = () => {
  if (store.busy) return
  workshopPublish.open = false
  workshopPublish.queue = []
  workshopPublish.modId = ''
}

const confirmDeleteMods = async token => {
  try {
    await store.deleteModFiles(token)
    showDeleteMods.value = false
  } catch { /* shared toast */ }
}

const submitWorkshopPublish = async publishData => {
  if (!workshopPublishMod.value) return
  try {
    const completedId = workshopPublishMod.value.id
    await store.publishWorkshopItem(completedId, publishData)
    const remaining = workshopPublish.queue.filter(modId => modId !== completedId && store.modMap.has(modId))
    if (remaining.length) {
      workshopPublish.queue = remaining
      workshopPublish.modId = remaining[0]
    } else {
      workshopPublish.open = false
      workshopPublish.queue = []
      workshopPublish.modId = ''
    }
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const createModType = async name => {
  try { await store.createModType(name) } catch { /* shared toast */ }
}

const updateModType = async ({ id, name }) => {
  try { await store.updateModType(id, name) } catch { /* shared toast */ }
}

const moveModType = async ({ id, direction }) => {
  const ids = store.modTypes.map(type => type.id)
  const index = ids.indexOf(id)
  const target = index + Number(direction || 0)
  if (index < 0 || target < 0 || target >= ids.length) return
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  try { await store.reorderModTypes(ids) } catch { /* shared toast */ }
}

const deleteModType = async typeId => {
  try { await store.deleteModType(typeId) } catch { /* shared toast */ }
}

const enterManualModType = async (modIds, initialMod = null) => {
  const currentType = initialMod?.mod_types?.[0] || initialMod?.mod_type || 'unknown'
  const currentTypeRecord = store.modTypes.find(type => type.id === currentType)
  const raw = window.prompt(
    t('context.manualType'),
    currentTypeRecord ? localizedModTypeName(currentTypeRecord) : '',
  )
  const name = String(raw || '').trim()
  if (!name) return
  const normalized = name.toLocaleLowerCase()
  let type = store.modTypes.find(item => (
    localizedModTypeName(item).trim().toLocaleLowerCase() === normalized
    || String(item.name || '').trim().toLocaleLowerCase() === normalized
  ))
  if (!type) type = await store.createModType(name)
  for (const modId of modIds) {
    const target = store.modMap.get(modId)
    if (!target) continue
    const selected = target.mod_types?.length ? target.mod_types : [target.mod_type || 'unknown']
    if (!selected.includes(type.id)) await store.toggleModType(modId, type.id)
  }
}

const syncWorkshopToData = async () => {
  const confirmed = await requestConfirmation({
    message: t('app.confirmSyncData'),
  })
  if (!confirmed) return
  try { await store.syncWorkshopToData() } catch { /* shared toast */ }
}

const selectWarning = async item => {
  if (!item.modId) return
  await store.selectMod(item.modId)
  showWarnings.value = false
}

const ignoreWarning = async item => {
  if (!item.ignorable || !item.code) return
  try {
    if (item.modId) {
      await store.setModWarningIgnored(item.modId, item.code, true)
      store.notify(t('app.warningIgnored', {
        name: item.modName,
        warning: persistentWarningLabel(item.code),
      }))
    } else {
      store.ignoreScanWarning(item.code)
      store.notify(t('app.scanWarningIgnored'))
    }
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const subscribeAndEnableDependencies = async item => {
  try {
    await store.subscribeAndEnableMissingDependencies([item])
    showWarnings.value = false
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const updateWarningMod = async item => {
  if (!item?.modId) return
  try {
    await store.forceUpdateWorkshop(item.modId)
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const updateAllWarningMods = async () => {
  const targets = store.warningItems.filter(item => (
    item.code === 'workshop_update_available' && !!item.modId
  ))
  if (!targets.length) return
  let completed = 0
  let failed = 0
  for (const item of targets) {
    try {
      await store.forceUpdateWorkshop(item.modId)
      completed += 1
    } catch {
      failed += 1
    }
  }
  try {
    await store.scan(false)
  } catch {
    // Store actions surface failures through the shared toast.
  }
  store.notify(
    t('toast.warningUpdateAllCompleted', { completed, failed }),
    failed ? 'warning' : 'success',
  )
}

const openSaveGames = async () => {
  showSaveGames.value = true
  try { await store.loadSaveGames() } catch { /* shared toast */ }
}

const launchSave = async saveName => {
  try {
    await store.launchSave(saveName)
    showSaveGames.value = false
  } catch { /* shared toast */ }
}

const launchOrTerminateGame = async () => {
  try {
    if (store.runtime.running) {
      const confirmed = await requestConfirmation({
        message: t('app.confirmTerminateGame'),
        confirmLabel: t('app.terminateGame'),
        danger: true,
      })
      if (!confirmed) return
      await store.terminateGame()
      return
    }
    await store.launch()
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const createSavePlayset = async saveName => {
  try {
    await store.createPlaysetFromSave(saveName)
    showSaveGames.value = false
  } catch { /* shared toast */ }
}

const compareSaveMods = async saveName => {
  try {
    saveModsComparison.value = await store.compareSaveMods(saveName)
    showSaveModsComparison.value = true
  } catch { /* shared toast */ }
}

const beginOfficialProfileImport = async () => {
  if (!supportsWh3Tools.value) return
  try {
    const selected = await store.selectOfficialProfile()
    if (!selected.path) return
    officialProfilePreview.value = await store.previewOfficialProfile(selected.path)
    showShare.value = false
    showOfficialProfileImport.value = true
  } catch { /* shared toast */ }
}

const importOfficialProfile = async ({ mode, subscribeMissing }) => {
  const preview = officialProfilePreview.value
  if (!preview) return
  try {
    const workshopIds = [...new Set((preview.unsubscribed || []).map(item => item.workshop_id))]
    if (subscribeMissing && workshopIds.length) await store.subscribeWorkshopItems(workshopIds)
    await store.importOfficialProfile(preview.profile.path, mode)
    showOfficialProfileImport.value = false
  } catch { /* shared toast */ }
}

const refreshDiagnostics = async (open = true) => {
  if (!supportsPackActions.value || diagnosticsPolling) return
  diagnosticsPolling = true
  const revision = diagnosticsViewRevision
  const game = activeGame.value
  try {
    const session = await store.getModDiagnostics()
    if (revision !== diagnosticsViewRevision || game !== activeGame.value) return
    diagnosticSession.value = session
    if (!session.running) {
      const diagnosis = await store.getCrashDiagnosis()
      const history = await store.getDiagnosticsHistory()
      if (revision !== diagnosticsViewRevision || game !== activeGame.value) return
      crashDiagnosis.value = diagnosis
      diagnosticHistory.value = history
    }
    if (open || session.running || crashDiagnosis.value.should_notify) showDiagnostics.value = true
  } catch (error) {
    if (open) store.notify(error.message, 'error')
  } finally { diagnosticsPolling = false }
}

const diagnosticAction = async action => {
  if (diagnosticsBusy.value) return
  diagnosticsBusy.value = true
  try { await action(); await refreshDiagnostics(true) }
  catch (error) { store.notify(error.message, 'error') }
  finally { diagnosticsBusy.value = false }
}

const startDiagnostics = mode => diagnosticAction(async () => {
  diagnosticSession.value = await store.startModDiagnostics(mode)
})
const confirmDiagnosticTrial = result => diagnosticAction(async () => {
  diagnosticSession.value = await store.confirmDiagnosticTrial(result)
})
const cancelDiagnostics = () => diagnosticAction(() => store.cancelModDiagnostics())
const applyDiagnosticResult = async (run, restore = false) => {
  const confirmed = await requestConfirmation({
    message: restore ? t('diagnostics.restoreConfirm')
      : t('diagnostics.applyConfirm', { count: run.excluded_ids?.length || 0 }),
    confirmLabel: t(restore ? 'diagnostics.restore' : 'diagnostics.apply'),
  })
  if (confirmed) await diagnosticAction(() => store.applyDiagnosticsResult(run.id, restore))
}
const closeDiagnostics = () => {
  if (diagnosticSession.value.running) return
  diagnosticsViewRevision += 1
  showDiagnostics.value = false
  void store.dismissCrashDiagnosis().catch(() => {})
}
watch(() => store.runtime.running, (running, previous) => {
  if (previous && !running && !diagnosticSession.value.running) void refreshDiagnostics(false)
})
watch(activeGame, () => {
  diagnosticsViewRevision += 1
  showDiagnostics.value = false
  diagnosticSession.value = { status: 'idle', running: false }
  crashDiagnosis.value = {}
  diagnosticHistory.value = []
  folderDialog.open = false
})
watch(() => store.currentPlaysetId, () => { folderDialog.open = false })

onMounted(() => {
  initialize()
  runtimeTimer = window.setInterval(() => {
    void store.refreshRuntime()
    if (showDiagnostics.value || diagnosticSession.value.running) void refreshDiagnostics(false)
  }, 1000)
  window.addEventListener('keydown', handleGlobalShortcut)
})

onBeforeUnmount(() => {
  completeConfirmation(false)
  window.clearInterval(runtimeTimer)
  window.clearTimeout(updateTimer)
  window.removeEventListener('keydown', handleGlobalShortcut)
})
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand-block">
        <div class="brand-shield">W</div>
        <div>
          <span class="brand-kicker">WYCCC'S</span>
          <h1>Mod Manager</h1>
        </div>
        <span class="version-pill">v{{ store.appVersion }}</span>
      </div>

      <div class="header-center">
        <div class="playset-select">
          <span>{{ t('app.playset') }}</span>
          <ThemedSelect
            :model-value="store.currentPlaysetId"
            :options="playsetOptions"
            :disabled="!!store.busy"
            :aria-label="t('app.playset')"
            data-testid="playset-select"
            @change="choosePlayset"
          />
        </div>
        <button type="button" class="header-button" :disabled="!!store.busy" @click="createPlayset">{{ t('app.newPlayset') }}</button>
        <button
          type="button"
          class="header-button"
          :disabled="!!store.busy || !store.currentPlayset || store.currentPlayset.is_default"
          @click="renamePlayset"
        >
          {{ t('common.rename') }}
        </button>
        <button
          type="button"
          class="header-button danger-text"
          :disabled="!!store.busy || !store.currentPlayset || store.currentPlayset.is_default"
          @click="deletePlayset"
        >
          {{ t('common.delete') }}
        </button>
        <button
          type="button"
          class="header-button"
          :disabled="!!store.busy || !store.currentPlayset"
          data-testid="playset-hidden-mods-toggle"
          @click="toggleCurrentPlaysetHiddenMods"
        >
          {{ t(store.showHidden ? 'app.hideHidden' : 'app.showHidden') }}
        </button>
      </div>

      <div class="header-actions">
        <span class="header-mod-count">
          {{ t('app.packCount', { count: store.mods.length }) }} · {{ t('app.enabledCount', { count: store.activeIds.length }) }}
        </span>
        <button type="button" class="header-button" @click="openShare">{{ t('app.importExport') }}</button>
        <button type="button" class="header-button" @click="showSettings = true">{{ t('app.settings') }}</button>
      </div>
    </header>

    <div v-if="!store.pathHealth.game_ready" class="path-warning">
      <strong>{{ t('app.pathMissingTitle') }}</strong>
      <span>{{ t('app.pathMissingDetail') }}</span>
      <button type="button" class="secondary-button" @click="showSettings = true">{{ t('app.configureNow') }}</button>
    </div>

    <main class="workspace-grid">
      <ModDetails
        :mod="store.selectedMod"
        :preview="store.selectedPreview"
        :ai-enabled="!!store.settings.ai_enabled"
        :generate-user-data="store.generateModUserData"
        @save-user-data="store.saveModUserData"
        @open-folder="store.openModFolder"
        @open-workshop-folder="store.openWorkshopFolder"
        @open-workshop="store.openWorkshop"
      />

      <ModList
        :title="t('app.inactiveMods')"
        :mods="store.inactiveMods"
        :folders="store.modFolders"
        :busy="!!store.busy"
        :warnings-only="store.warningsOnly"
        :selected-id="store.selectedId"
        :selected-ids="store.selectedIds"
        :order-ids="store.inactiveOrderIds"
        :thumbnails="store.thumbnails"
        :type-map="store.modTypeMap"
        :visual-sorted="store.inactiveSortMode !== 'priority'"
        :search-tokens="store.inactiveSearchTokens"
        :search-logic="store.inactiveSearchLogic"
        :search-suggestion-mods="store.inactiveDisplayMods"
        search-test-id="inactive-mod-search"
        :search-highlight-mode="store.inactiveSearchHighlightMode"
        search-highlight-test-id="inactive-search-highlight-button"
        :sort-mode="store.inactiveSortMode"
        :sort-descending="store.inactiveSortDescending"
        sort-test-id="inactive-sort-button"
        :search-active="store.inactiveSearchHighlightActive"
        :search-match-ids="store.inactiveSearchMatchIds"
        :search-focus-id="inactiveSearchFocusId"
        :drag-source="modDragSource"
        :unit-data-mod-ids="unitDataModIds"
        @select="store.selectMod"
        @enable="enableSelected"
        @toggle-active="toggleSingleMod"
        @drop-mods="handleListDrop"
        @drag-start="startModDrag"
        @drag-end="endModDrag"
        @context-menu="openModContextMenu"
        @toggle-folder="toggleModFolder"
        @rename-folder="renameModFolder"
        @delete-folder="deleteModFolder"
        @open-unit-data="openUnitDataModification"
        @select-all="store.selectAllMods"
        @update:search-tokens="store.setInactiveSearchTokens"
        @update:search-logic="store.setInactiveSearchLogic"
        @toggle-search-highlight="toggleSearchHighlight('inactive')"
        @update:sort-mode="store.setInactiveSortMode"
        @update:sort-descending="store.setInactiveSortDescending"
      />

      <ModList
        :title="t('app.activeMods')"
        active
        :mods="store.activeMods"
        :folders="store.modFolders"
        :busy="!!store.busy"
        :selected-id="store.selectedId"
        :selected-ids="store.selectedIds"
        :order-ids="store.activeIds"
        :thumbnails="store.thumbnails"
        :type-map="store.modTypeMap"
        :visual-sorted="store.activeSortMode !== 'priority'"
        :search-tokens="store.activeSearchTokens"
        :search-logic="store.activeSearchLogic"
        :search-suggestion-mods="store.activeDisplayMods"
        search-test-id="active-mod-search"
        :search-highlight-mode="store.activeSearchHighlightMode"
        search-highlight-test-id="active-search-highlight-button"
        :sort-mode="store.activeSortMode"
        :sort-descending="store.activeSortDescending"
        sort-test-id="active-sort-button"
        :search-active="store.activeSearchHighlightActive"
        :search-match-ids="store.activeSearchMatchIds"
        :search-focus-id="activeSearchFocusId"
        :warning-count="store.warningCount"
        :warnings-only="store.warningsOnly"
        :drag-source="modDragSource"
        :unit-data-mod-ids="unitDataModIds"
        @select="store.selectMod"
        @disable="disableSelected"
        @toggle-active="toggleSingleMod"
        @drop-mods="handleListDrop"
        @drag-start="startModDrag"
        @drag-end="endModDrag"
        @move="store.move"
        @toggle-folder="toggleModFolder"
        @rename-folder="renameModFolder"
        @delete-folder="deleteModFolder"
        @context-menu="openModContextMenu"
        @open-unit-data="openUnitDataModification"
        @select-all="store.selectAllMods"
        @show-warnings="showWarnings = true"
        @toggle-warnings-only="store.toggleWarningsOnly"
        @update:search-tokens="store.setActiveSearchTokens"
        @update:search-logic="store.setActiveSearchLogic"
        @toggle-search-highlight="toggleSearchHighlight('active')"
        @update:sort-mode="store.setActiveSortMode"
        @update:sort-descending="store.setActiveSortDescending"
      />
    </main>

    <footer class="action-footer">
      <div class="footer-left">
        <button
          v-if="supportsPackActions"
          type="button"
          class="secondary-button sync-data-button footer-sync-button"
          :disabled="!!store.busy || store.runtime.running || store.workshopRefreshing || !store.pathHealth.game_ready || !store.pathHealth.workshop_path_exists"
          :title="store.runtime.running ? t('context.gameRunningBlocked') : ''"
          data-testid="sync-data-button"
          @click="syncWorkshopToData"
        >
          {{ t('app.syncData') }}
        </button>

        <button type="button" class="secondary-button sync-data-button" :disabled="!!store.busy || store.workshopRefreshing || !store.pathHealth.game_ready" @click="store.scan(false)">
          {{ t('app.rescan') }}
        </button>
        <button type="button" class="secondary-button sync-data-button" :disabled="!!store.busy || store.workshopRefreshing || !store.pathHealth.game_ready" @click="store.refreshWorkshopInBackground">
          {{ t('app.refreshWorkshop') }}
        </button>
        <button type="button" class="secondary-button sync-data-button" :disabled="!!store.busy || !store.pathHealth.game_ready" @click="store.openGameFolder">
          {{ t('app.openGameFolder') }}
        </button>
        <button
          v-if="supportsWh3Tools"
          type="button"
          class="secondary-button sync-data-button footer-edit-button"
          :disabled="!!store.busy || store.runtime.running"
          data-testid="game-data-modification-button"
          @click="openGameDataModification"
        >
          {{ t('app.gameDataModification') }}
        </button>
        <button
          v-if="supportsUnitDataTools"
          type="button"
          class="secondary-button sync-data-button footer-edit-button"
          :disabled="!!store.busy || store.runtime.running"
          data-testid="unit-data-modification-button"
          @click="openUnitDataModification"
        >
          {{ t('app.unitDataModification') }}
        </button>
        <button
          v-if="supportsWh3Tools"
          type="button"
          class="secondary-button sync-data-button"
          :disabled="!!store.busy || store.orderSaving || store.dirty || !store.pathHealth.game_ready"
          data-testid="unit-encyclopedia-button"
          @click="showUnitEncyclopedia = true"
        >
          {{ t('encyclopedia.title') }}
        </button>
        <button
          v-if="supportsWh3Tools"
          type="button"
          class="secondary-button sync-data-button"
          :disabled="!!store.busy || store.runtime.running"
          data-testid="compatibility-patch-button"
          @click="openCompatibilityPatch"
        >
          {{ t('app.compatibilityPatch') }}
        </button>
        <button v-if="supportsPackActions" type="button" class="secondary-button sync-data-button footer-diagnostics-button"
          :disabled="!!store.busy || !store.pathHealth.game_ready" data-testid="mod-diagnostics-button"
          @click="refreshDiagnostics(true)">{{ t('diagnostics.title') }}</button>
      </div>

      <div class="footer-status" :class="`status-${statusDisplay.kind}`">
        <span v-if="statusDisplay.spinning" class="spinner"></span>
        {{ statusDisplay.text }}
      </div>

      <div class="footer-actions">
        <button
          v-if="supportsSaveGames"
          type="button"
          class="secondary-button save-list-button"
          :disabled="!!store.busy || !store.pathHealth.game_ready || store.runtime.running"
          @click="openSaveGames"
        >
          {{ t('app.saveList') }}
        </button>
        <button
          v-if="supportsSaveGames"
          type="button"
          class="continue-button"
          :disabled="!!store.busy || !store.pathHealth.game_ready || store.runtime.running"
          @click="store.continueGame"
        >
          {{ t('app.continueGame') }}
        </button>
        <button
          type="button"
          class="launch-button"
          :disabled="!!store.busy || !store.pathHealth.game_ready"
          @click="launchOrTerminateGame"
        >
          <span class="play-mark">{{ store.runtime.running ? '■' : '▶' }}</span>
          {{ store.runtime.running ? t('app.terminateGame') : t('app.launchGame') }}
        </button>
      </div>
    </footer>

    <SettingsModal
      :open="showSettings"
      :settings="store.settings"
      :health="store.pathHealth"
      :busy="store.busy"
      @close="showSettings = false"
      @save="saveSettings"
      @detect="detectPaths"
      @check-update="checkForUpdates"
      @show-changelog="openChangelog"
    />

    <GameDataModificationModal
      v-if="supportsWh3Tools"
      :open="showGameDataModification"
      :settings="store.settings"
      :busy="store.busy"
      :unit-size-subscribed="!!unitSizeFeature.subscribed"
      :friendly-fire-subscribed="!!friendlyFireFeature.subscribed"
      :unit-capacity-subscribed="!!unitCapFeature.subscribed"
      :unit-size-mod-name="unitSizeFeature.title"
      :friendly-fire-mod-name="friendlyFireFeature.title"
      :unit-capacity-mod-name="unitCapFeature.title"
      @close="showGameDataModification = false"
      @save="saveGameDataSettings"
    />

    <UnitEncyclopediaModal
      v-if="supportsWh3Tools" :open="showUnitEncyclopedia"
      :suspended="showUnitDataModification || confirmationDialog.open"
      :edit-disabled="!!store.busy || store.orderSaving || store.runtime.running || openingUnitDataModification"
      :refresh-key="unitEncyclopediaRevision"
      @edit-unit="(key, token) => openUnitDataModification(null, key, token)"
      @close="showUnitEncyclopedia = false"
    />

    <UnitDataModificationModal
      v-if="supportsUnitDataTools"
      :open="showUnitDataModification"
      :busy="store.busy"
      :game-id="activeGame"
      :initial-search="unitDataSearch"
      :initial-unit-key="unitDataUnitKey"
      :snapshot-token="unitDataSnapshotToken"
      @close="showUnitDataModification = false"
      @save="saveUnitData"
    />

    <ModDiagnosticsModal
      :open="showDiagnostics" :session="diagnosticSession" :diagnosis="crashDiagnosis"
      :history="diagnosticHistory" :busy="diagnosticsBusy" :game-running="store.runtime.running"
      :enabled-count="store.activeIds.length"
      @close="closeDiagnostics" @refresh="refreshDiagnostics(true)" @start="startDiagnostics"
      @confirm-trial="confirmDiagnosticTrial" @cancel="cancelDiagnostics"
      @apply="applyDiagnosticResult($event)" @restore="applyDiagnosticResult($event, true)"
    />
    <CompatibilityPatchModal
      v-if="supportsWh3Tools"
      :open="showCompatibilityPatch"
      :settings="store.settings"
      :busy="store.busy"
      :required-packs-enabled="nanuRorPackRequirement.allEnabled"
      :missing-packs="nanuRorPackRequirement.missing"
      :variant-selector-packs-enabled="variantSelectorPackRequirement.allEnabled"
      :variant-selector-missing-packs="variantSelectorPackRequirement.missing"
      @close="showCompatibilityPatch = false"
      @save="saveCompatibilityPatch"
    />

    <UpdateModal
      :open="updateDialog.open"
      :mode="updateDialog.mode"
      :info="store.updateInfo"
      :changelog="store.changelog"
      :busy="store.busy"
      @close="closeUpdateDialog"
      @download="downloadUpdate"
      @install="installUpdate"
      @ignore="ignoreUpdate"
    />

    <SaveGamesModal
      :open="showSaveGames"
      :saves="store.saveGames"
      :directory="store.saveGamesDirectory"
      :busy="store.busy"
      :running="store.runtime.running"
      @close="showSaveGames = false"
      @refresh="store.loadSaveGames"
      @load="launchSave"
      @create-playset="createSavePlayset"
      @compare-mods="compareSaveMods"
    />

    <SaveModsComparisonModal
      :open="showSaveModsComparison"
      :comparison="saveModsComparison"
      @close="showSaveModsComparison = false"
    />

    <WarningModal
      :open="showWarnings"
      :items="store.warningItems"
      :busy="store.busy"
      @close="showWarnings = false"
      @select="selectWarning"
      @ignore="ignoreWarning"
      @subscribe-enable="subscribeAndEnableDependencies"
      @update="updateWarningMod"
      @update-all="updateAllWarningMods"
    />

    <ShareModal
      :open="showShare"
      :export-value="shareValue"
      :busy="store.busy"
      :can-import-official-profile="supportsWh3Tools"
      @close="showShare = false"
      @export="exportShare"
      @import="importShare"
      @import-collection="importWorkshopCollection"
      @import-official="beginOfficialProfileImport"
    />

    <OfficialProfileImportModal
      :open="showOfficialProfileImport"
      :preview="officialProfilePreview"
      :busy="store.busy"
      @close="showOfficialProfileImport = false"
      @import="importOfficialProfile"
    />

    <TypeManagerModal
      :open="showTypeManager"
      :types="store.modTypes"
      :busy="store.busy"
      @close="showTypeManager = false"
      @create="createModType"
      @update="updateModType"
      @move="moveModType"
      @delete="deleteModType"
    />

    <WorkshopPublishModal
      :open="workshopPublish.open"
      :mode="workshopPublish.mode"
      :mod="workshopPublishMod"
      :busy="store.busy"
      @close="closeWorkshopPublish"
      @submit="submitWorkshopPublish"
    />

    <ModContextMenu
      :open="contextMenu.open"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :mod="contextMod"
      :active="contextModActive"
      :types="store.modTypes"
      :selection-count="contextSelectionCount"
      :selected-mod-ids="contextSelectionIds"
      :eligible-update-ids="[...store.workshopUpdateEligibility]"
      :ai-enabled="!!store.settings.ai_enabled"
      :game-running="store.runtime.running"
      :keyboard-shortcuts="store.settings.keyboard_shortcuts"
      :busy="!!store.busy"
      :pack-actions="supportsPackActions"
      :folders="store.modFolders"
      @close="closeModContextMenu"
      @action="handleContextAction"
    />

    <SchemaUpdateModal :open="schemaUpdate.open" :pending="schemaUpdate.pending"
      :report="schemaUpdate.report" :error="schemaUpdate.error" @close="schemaUpdate.open = false" />

    <DeleteModsModal
      :open="showDeleteMods"
      :preview="deleteModsPreview"
      :busy="store.busy"
      @close="showDeleteMods = false"
      @confirm="confirmDeleteMods"
    />

    <FolderNameModal
      :open="folderDialog.open"
      :rename="folderDialog.rename"
      :initial-name="folderDialog.name"
      :busy="!!store.busy"
      :error="folderDialog.error"
      @close="folderDialog.open = false"
      @submit="submitModFolderName"
    />

    <ConfirmationModal
      :open="confirmationDialog.open"
      :message="confirmationDialog.message"
      :confirm-label="confirmationDialog.confirmLabel"
      :danger="confirmationDialog.danger"
      @close="completeConfirmation(false)"
      @confirm="completeConfirmation(true)"
    />

    <transition name="toast">
      <div v-if="store.toast" class="toast" :class="store.toast.type">
        {{ store.toast.message }}
      </div>
    </transition>
  </div>
</template>
