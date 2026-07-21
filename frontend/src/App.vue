<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { localizedModTypeName, localizedPlaysetName, t } from './languages'
import { executeKeyboardShortcut, resolveKeyboardShortcut } from './keyboardShortcuts'
import { useAppStore } from './store'
import DeleteModsModal from './components/DeleteModsModal.vue'
import GameDataModificationModal from './components/GameDataModificationModal.vue'
import ModContextMenu from './components/ModContextMenu.vue'
import ModDetails from './components/ModDetails.vue'
import ModList from './components/ModList.vue'
import OfficialProfileImportModal from './components/OfficialProfileImportModal.vue'
import SaveGamesModal from './components/SaveGamesModal.vue'
import SaveModsComparisonModal from './components/SaveModsComparisonModal.vue'
import SettingsModal from './components/SettingsModal.vue'
import ShareModal from './components/ShareModal.vue'
import SortMenu from './components/SortMenu.vue'
import TagSearchBox from './components/TagSearchBox.vue'
import ThemedSelect from './components/ThemedSelect.vue'
import TypeManagerModal from './components/TypeManagerModal.vue'
import UpdateModal from './components/UpdateModal.vue'
import WarningModal from './components/WarningModal.vue'
import WorkshopPublishModal from './components/WorkshopPublishModal.vue'

const store = useAppStore()
const showGameDataModification = ref(false)
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
const updateDialog = reactive({ open: false, mode: 'update' })
const shareValue = ref('')
const contextMenu = reactive({ open: false, x: 0, y: 0, modId: '' })
const workshopPublish = reactive({ open: false, mode: 'upload', modId: '', queue: [] })
let runtimeTimer = 0
let updateTimer = 0

const contextMod = computed(() => store.modMap.get(contextMenu.modId) || null)
const contextModActive = computed(() => !!contextMod.value && store.activeIds.includes(contextMod.value.id))
const activeGame = computed(() => store.settings.selected_game || 'warhammer3')
const supportsWh3Tools = computed(() => activeGame.value === 'warhammer3')
const unitSizeFeature = computed(() => store.gameDataFeatures.unit_size)
const friendlyFireFeature = computed(() => store.gameDataFeatures.friendly_fire)
const unitCapFeature = computed(() => store.gameDataFeatures.unit_cap)
const workshopPublishMod = computed(() => store.modMap.get(workshopPublish.modId) || null)
const searchFocusId = computed(() => (
  store.searchHighlightActive
    ? store.inactiveSearchMatchIds[0] || store.activeSearchMatchIds[0] || ''
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

watch(supportsWh3Tools, supported => {
  if (supported) return
  showGameDataModification.value = false
  showOfficialProfileImport.value = false
  officialProfilePreview.value = null
})

const initialize = async () => {
  try {
    const bootstrap = await store.bootstrap()
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
  if (!window.confirm(t('app.confirmDeletePlayset', {
    name: store.currentPlayset.name,
    defaultName: t('common.default'),
  }))) return
  try { await store.deleteCurrentPlayset() } catch { /* shared toast */ }
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
      const confirmed = window.confirm(
        t('app.confirmSubscribe', { items: visibleItems.join('\n') }),
      )
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
const toggleSearchHighlight = async () => {
  try {
    await store.setSearchHighlightMode(!store.searchHighlightMode)
  } catch {
    // Store actions surface failures through the shared toast.
  }
}

const shortcutsBlocked = () => (
  showGameDataModification.value
  || showSettings.value
  || showShare.value
  || showTypeManager.value
  || showWarnings.value
  || showSaveGames.value
  || showSaveModsComparison.value
  || showOfficialProfileImport.value
  || showDeleteMods.value
  || updateDialog.open
  || contextMenu.open
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

const handleContextAction = async ({ action, value, mod }) => {
  if (!mod) return
  const actionIds = [...selectedActionIds(mod.id)]
  try {
    if (action === 'toggle-active') {
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
      if (!window.confirm(t('app.confirmUnsubscribe', { subject }))) return
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
      const warningLabel = value === 'missing_dependency'
        ? t('app.warningMissingDependency')
        : t('app.warningOutdated')
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
  const confirmed = window.confirm(t('app.confirmSyncData'))
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
        warning: item.code === 'missing_dependency'
          ? t('app.warningMissingDependency')
          : t('app.warningOutdated'),
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

onMounted(() => {
  initialize()
  runtimeTimer = window.setInterval(() => store.refreshRuntime(), 1000)
  window.addEventListener('keydown', handleGlobalShortcut)
})

onBeforeUnmount(() => {
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
      </div>

      <div class="header-actions">
        <button type="button" class="header-button" @click="openShare">{{ t('app.importExport') }}</button>
        <button type="button" class="header-button" @click="showSettings = true">{{ t('app.settings') }}</button>
      </div>
    </header>

    <div v-if="!store.pathHealth.game_ready" class="path-warning">
      <strong>{{ t('app.pathMissingTitle') }}</strong>
      <span>{{ t('app.pathMissingDetail') }}</span>
      <button type="button" class="secondary-button" @click="showSettings = true">{{ t('app.configureNow') }}</button>
    </div>

    <div class="workspace-toolbar">
      <div class="toolbar-search-cluster">
        <TagSearchBox
          :tokens="store.searchTokens"
          :logic="store.searchLogic"
          :mods="store.mods"
          :type-map="store.modTypeMap"
          @update:tokens="store.setSearchTokens"
          @update:logic="store.setSearchLogic"
        />
        <button
          type="button"
          class="search-highlight-button"
          :class="{ active: store.searchHighlightMode }"
          :aria-pressed="store.searchHighlightMode"
          :title="t('search.highlightModeHelp')"
          :aria-label="t('search.highlightModeHelp')"
          data-testid="search-highlight-button"
          @click="toggleSearchHighlight"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="5.5"></circle>
            <path d="m15.2 15.2 4.3 4.3M11 8.5v5M8.5 11h5"></path>
          </svg>
        </button>
        <SortMenu
          :mode="store.sortMode"
          :descending="store.sortDescending"
          @update:mode="store.setSortMode"
          @update:descending="store.setSortDescending"
        />
        <button
          type="button"
          class="hidden-visibility-button"
          :class="{ active: store.showHidden }"
          :disabled="!store.hiddenCount"
          :title="store.hiddenCount ? (store.showHidden ? t('app.hideHidden') : t('app.showHidden')) : t('app.noHidden')"
          data-testid="hidden-visibility-button"
          @click="store.toggleHiddenVisibility"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M2.5 12s3.4-5 9.5-5 9.5 5 9.5 5-3.4 5-9.5 5-9.5-5-9.5-5Z"></path>
            <circle cx="12" cy="12" r="2.4"></circle>
            <path v-if="!store.showHidden" d="m4 4 16 16"></path>
          </svg>
          <span v-if="store.hiddenCount">{{ store.hiddenCount }}</span>
        </button>
      </div>
      <div class="toolbar-meta">
        <span>{{ t('app.packCount', { count: store.mods.length }) }}</span>
        <span>{{ t('app.enabledCount', { count: store.activeIds.length }) }}</span>
        <span v-if="store.selectedIds.length > 1" class="selection-indicator">{{ t('app.selectedCount', { count: store.selectedIds.length }) }}</span>
        <span v-if="store.workshopRefreshing" class="running-indicator">{{ t('app.backgroundWorkshop') }}</span>
        <span v-if="store.runtime.running" class="running-indicator">{{ t('status.gameRunning') }}</span>
      </div>
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
        :selected-id="store.selectedId"
        :selected-ids="store.selectedIds"
        :order-ids="store.inactiveOrderIds"
        :thumbnails="store.thumbnails"
        :type-map="store.modTypeMap"
        :visual-sorted="store.sortMode !== 'priority'"
        :search-active="store.searchHighlightActive"
        :search-match-ids="store.inactiveSearchMatchIds"
        :search-focus-id="searchFocusId"
        @select="store.selectMod"
        @enable="enableSelected"
        @toggle-active="toggleSingleMod"
        @drop-mods="handleListDrop"
        @context-menu="openModContextMenu"
        @select-all="store.selectAllMods"
      />

      <ModList
        :title="t('app.activeMods')"
        active
        :mods="store.activeMods"
        :selected-id="store.selectedId"
        :selected-ids="store.selectedIds"
        :order-ids="store.activeIds"
        :thumbnails="store.thumbnails"
        :type-map="store.modTypeMap"
        :visual-sorted="store.sortMode !== 'priority'"
        :search-active="store.searchHighlightActive"
        :search-match-ids="store.activeSearchMatchIds"
        :search-focus-id="searchFocusId"
        :warning-count="store.warningCount"
        @select="store.selectMod"
        @disable="disableSelected"
        @toggle-active="toggleSingleMod"
        @drop-mods="handleListDrop"
        @move="store.move"
        @context-menu="openModContextMenu"
        @select-all="store.selectAllMods"
        @show-warnings="showWarnings = true"
      />
    </main>

    <footer class="action-footer">
      <div class="footer-left">
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
          class="secondary-button sync-data-button"
          :disabled="!!store.busy || store.runtime.running"
          data-testid="game-data-modification-button"
          @click="openGameDataModification"
        >
          {{ t('app.gameDataModification') }}
        </button>
        <button
          type="button"
          class="secondary-button sync-data-button"
          :disabled="!!store.busy || store.workshopRefreshing || !store.pathHealth.game_ready || !store.pathHealth.workshop_path_exists"
          @click="syncWorkshopToData"
        >
          {{ t('app.syncData') }}
        </button>
      </div>

      <div class="footer-status" :class="`status-${statusDisplay.kind}`">
        <span v-if="statusDisplay.spinning" class="spinner"></span>
        {{ statusDisplay.text }}
      </div>

      <div class="footer-actions">
        <button
          type="button"
          class="secondary-button save-list-button"
          :disabled="!!store.busy || !store.pathHealth.game_ready || store.runtime.running"
          @click="openSaveGames"
        >
          {{ t('app.saveList') }}
        </button>
        <button
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
          :disabled="!!store.busy || !store.pathHealth.game_ready || store.runtime.running"
          @click="store.launch"
        >
          <span class="play-mark">▶</span>
          {{ store.runtime.running ? t('app.gameRunningShort') : t('app.launchGame') }}
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
      @close="closeModContextMenu"
      @action="handleContextAction"
    />

    <DeleteModsModal
      :open="showDeleteMods"
      :preview="deleteModsPreview"
      :busy="store.busy"
      @close="showDeleteMods = false"
      @confirm="confirmDeleteMods"
    />

    <transition name="toast">
      <div v-if="store.toast" class="toast" :class="store.toast.type">
        {{ store.toast.message }}
      </div>
    </transition>
  </div>
</template>
