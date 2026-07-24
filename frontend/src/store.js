import { defineStore } from 'pinia'
import { invoke } from './bridge'
import {
  applyInterfaceLanguage,
  localizedModTypeName,
  localizedPlaysetName,
  localizeBackendMessage,
  t,
} from './languages'
import {
  insertByDefaultLoadOrder,
  matchesSearchTokens,
  SORT_OPTIONS,
  sortDisplayedMods,
} from './modSearch'

let playsetWriteQueue = Promise.resolve()
let collectionImportPollTimer = 0
const COLLECTION_IMPORT_POLL_INTERVAL_MS = 4_000

const defaultGameDataFeatures = () => ({
  unit_size: {
    workshop_id: '3765783838',
    title: 'Dynamic Unit Size',
    pack_name: 'wyccc_dynamic_unit_size.pack',
    subscribed: false,
  },
  friendly_fire: {
    workshop_id: '3765783977',
    title: 'Dynamic No Friendly Fire',
    pack_name: 'wyccc_dynamic_no_friendly_fire.pack',
    subscribed: false,
  },
  unit_cap: {
    workshop_id: '3766867060',
    title: '动态单位容量 - Dynamic Unit Cap',
    pack_name: 'wyccc_dynamic_unit_cap.pack',
    subscribed: false,
  },
})

const localizedSelectedGameName = settings => t(
  settings?.selected_game === 'three_kingdoms'
    ? 'settings.gameThreeKingdoms'
    : 'settings.gameWarhammer3',
)

const enqueuePlaysetWrite = task => {
  const pending = playsetWriteQueue.catch(() => {}).then(task)
  playsetWriteQueue = pending
  return pending
}

const pendingWorkshopId = value => {
  const match = String(value || '').match(/^pending:steam:(\d+):/)
  return match?.[1] || ''
}

const sameIds = (left, right) => (
  left.length === right.length && left.every((value, index) => value === right[index])
)

export const useAppStore = defineStore('app', {
  state: () => ({
    appName: "Wyccc's Mod Manager",
    appVersion: '0.9.4',
    settings: {},
    paths: {},
    pathHealth: {},
    mods: [],
    modTypes: [],
    activeIds: [],
    inactiveOrderIds: [],
    inactiveOrderCustomized: false,
    selectedId: '',
    selectedIds: [],
    selectionAnchorId: '',
    selectedPreview: '',
    thumbnails: {},
    activeSearchTokens: [],
    activeSearchLogic: 'AND',
    inactiveSearchTokens: [],
    inactiveSearchLogic: 'AND',
    activeSortMode: 'priority',
    activeSortDescending: false,
    inactiveSortMode: 'priority',
    inactiveSortDescending: false,
    playsets: [],
    currentPlaysetId: 'default',
    backups: [],
    orderToken: 'missing',
    dirty: false,
    orderSaving: false,
    orderSavePending: 0,
    orderSaveError: '',
    busy: '',
    workshopRefreshing: false,
    liveModRefreshing: false,
    collectionImportSync: null,
    warnings: [],
    ignoredScanWarningCodes: [],
    gameUpdatedAt: 0,
    missingEnabledIds: [],
    runtime: { running: false, mod_revision: 0 },
    modRevision: 0,
    saveGames: [],
    saveGamesDirectory: '',
    changelog: [],
    updateInfo: null,
    updateChecking: false,
    autoUpdateDue: false,
    toast: null,
    gameDataFeatures: defaultGameDataFeatures(),
    gameDataFeatureWarning: '',
    workshopUpdateEligibility: new Set(),
    workshopEligibilityRequestId: 0,
  }),
  getters: {
    modMap: (state) => new Map(state.mods.map(mod => [mod.id, mod])),
    gameDataFeatureSubscribed: (state) => featureKey => (
      Boolean(state.gameDataFeatures?.[featureKey]?.subscribed)
    ),
    modTypeMap: (state) => Object.fromEntries(state.modTypes.map(item => [item.id, localizedModTypeName(item)])),
    modTypeRanks: (state) => Object.fromEntries(state.modTypes.map((item, index) => [item.id, index])),
    hiddenCount: (state) => state.mods.filter(mod => mod.hidden).length,
    showHidden: state => Boolean(state.settings?.show_hidden_mods),
    warningItems(state) {
      const active = new Set(state.activeIds)
      const items = state.warnings
        .map((warning, index) => {
          const record = warning && typeof warning === 'object' ? warning : { message: warning }
          const code = String(record.code || '')
          return {
            id: `scan:${code || index}`,
            message: localizeBackendMessage(record.message, 'warnings.genericScan'),
            severity: record.severity || 'warning',
            modId: '',
            modName: '',
            code,
            ignorable: Boolean(record.ignorable && code),
            dependencies: Array.isArray(record.dependencies) ? record.dependencies : [],
          }
        })
        .filter(item => !item.code || !state.ignoredScanWarningCodes.includes(item.code))
      for (const mod of state.mods) {
        for (const [index, warning] of (mod.warnings || []).entries()) {
          const code = warning.code || ''
          if (code === 'missing_dependency' && !active.has(mod.id)) continue
          items.push({
            id: `${mod.id}:${code || index}`,
            message: localizeBackendMessage(warning.message || String(warning), 'warnings.genericScan'),
            severity: warning.severity || 'warning',
            modId: mod.id,
            modName: mod.effective_name || mod.display_name || mod.pack_name,
            code,
            ignorable: ['outdated_mod', 'missing_dependency'].includes(code),
            dependencies: Array.isArray(warning.dependencies) ? warning.dependencies : [],
          })
        }
      }
      return items
    },
    warningCount() {
      return this.warningItems.length
    },
    currentPlayset() {
      return this.playsets.find(item => item.id === this.currentPlaysetId) || null
    },
    selectedMod() {
      return this.modMap.get(this.selectedId) || null
    },
    activeSearchActive: state => state.activeSearchTokens.length > 0,
    inactiveSearchActive: state => state.inactiveSearchTokens.length > 0,
    activeSearchHighlightMode: state => Boolean(state.settings?.active_search_highlight_mode),
    inactiveSearchHighlightMode: state => Boolean(state.settings?.inactive_search_highlight_mode),
    activeSearchHighlightActive() {
      return this.activeSearchActive && this.activeSearchHighlightMode
    },
    inactiveSearchHighlightActive() {
      return this.inactiveSearchActive && this.inactiveSearchHighlightMode
    },
    activeDisplayMods() {
      const mods = this.activeIds
        .map(id => this.modMap.get(id))
        .filter(Boolean)
        .filter(mod => this.showHidden || !mod.hidden)
      return sortDisplayedMods(mods, this.activeSortMode, this.activeSortDescending, this.modTypeRanks)
    },
    inactiveDisplayMods() {
      const active = new Set(this.activeIds)
      const mods = this.mods
        .filter(mod => !active.has(mod.id))
        .filter(mod => this.showHidden || !mod.hidden)
      const sorted = sortDisplayedMods(
        mods,
        this.inactiveSortMode,
        this.inactiveSortDescending,
        this.modTypeRanks,
      )
      if (this.inactiveSortMode !== 'priority' || !this.inactiveOrderCustomized) return sorted
      const rank = new Map(this.inactiveOrderIds.map((id, index) => [id, index]))
      return [...mods].sort((left, right) => (
        (rank.get(left.id) ?? Number.MAX_SAFE_INTEGER)
        - (rank.get(right.id) ?? Number.MAX_SAFE_INTEGER)
      ))
    },
    activeSearchMatchIds() {
      if (!this.activeSearchActive) return []
      return this.activeDisplayMods
        .filter(mod => matchesSearchTokens(mod, this.activeSearchTokens, this.activeSearchLogic, this.modTypeMap))
        .map(mod => mod.id)
    },
    inactiveSearchMatchIds() {
      if (!this.inactiveSearchActive) return []
      return this.inactiveDisplayMods
        .filter(mod => matchesSearchTokens(mod, this.inactiveSearchTokens, this.inactiveSearchLogic, this.modTypeMap))
        .map(mod => mod.id)
    },
    activeMods() {
      if (this.activeSearchHighlightActive) return this.activeDisplayMods
      return this.activeDisplayMods.filter(mod => (
        matchesSearchTokens(mod, this.activeSearchTokens, this.activeSearchLogic, this.modTypeMap)
      ))
    },
    inactiveMods() {
      if (this.inactiveSearchHighlightActive) return this.inactiveDisplayMods
      return this.inactiveDisplayMods.filter(mod => (
        matchesSearchTokens(mod, this.inactiveSearchTokens, this.inactiveSearchLogic, this.modTypeMap)
      ))
    },
  },
  actions: {
    replaceActiveIds(modIds) {
      this.activeIds = [...new Set((modIds || []).map(id => String(id)).filter(Boolean))]
      this.refreshMissingDependencyWarnings()
    },
    refreshMissingDependencyWarnings() {
      // The backend evaluates both missing and installed-but-disabled
      // dependencies.  Keep its result intact while a playset write is queued;
      // rebuilding from `missing_dependencies` here would lose the latter.
    },
    applyMissingDependencyWarnings(warningsByModId) {
      if (!warningsByModId || typeof warningsByModId !== 'object') return
      for (const mod of this.mods) {
        const warnings = (mod.warnings || [])
          .filter(warning => warning?.code !== 'missing_dependency')
        const current = warningsByModId[mod.id]
        if (Array.isArray(current)) warnings.push(...current)
        mod.warnings = warnings
      }
    },
    notify(message, type = 'success') {
      this.toast = { message, type, id: Date.now() }
      window.setTimeout(() => {
        if (this.toast?.message === message) this.toast = null
      }, 3200)
    },
    async withBusy(label, task) {
      if (this.busy) throw new Error(t('busy.alreadyRunning', { task: this.busy }))
      this.busy = label
      try {
        return await task()
      } catch (error) {
        this.notify(error.message || String(error), 'error')
        throw error
      } finally {
        this.busy = ''
      }
    },
    async bootstrap() {
      const data = await this.withBusy(t('busy.initialize'), () => invoke('get_bootstrap'))
      this.appName = data.app_name
      this.appVersion = data.app_version
      this.settings = data.settings
      applyInterfaceLanguage(this.settings.language)
      this.paths = data.paths
      this.pathHealth = data.path_health
      this.replaceActiveIds(data.enabled_order)
      this.playsets = data.playsets || []
      this.currentPlaysetId = data.current_playset?.id || 'default'
      this.backups = data.backups
      this.modTypes = data.mod_types || []
      this.orderToken = data.order_token
      this.runtime = data.runtime
      this.modRevision = Number(data.runtime?.mod_revision || 0)
      this.changelog = data.changelog || []
      this.autoUpdateDue = Boolean(data.auto_update_due)
      if (this.pathHealth.game_ready) {
        await this.scan(false)
        if (this.settings.fetch_workshop_metadata) {
          window.setTimeout(() => {
            if (this.settings.fetch_workshop_metadata && !this.runtime.running) {
              void this.refreshWorkshopInBackground()
            }
          }, 1200)
        }
      }
      if (data.update_install_error) {
        const installError = String(data.update_install_error).slice(-320)
        this.notify(t('toast.updateRollback', { error: installError }), 'error')
      }
      return data
    },
    async scan(refreshWorkshop = false) {
      await this.flushPlaysetUpdates()
      return this.withBusy(refreshWorkshop ? t('busy.refreshWorkshop') : t('busy.scanMods'), async () => {
        const previousIds = [...this.activeIds]
        const preserveDirty = this.dirty
        const data = await invoke('scan_mods', refreshWorkshop)
        this.mods = data.mods
        const currentThumbnails = this.thumbnails
        this.thumbnails = Object.fromEntries(
          data.mods
            .filter(mod => currentThumbnails[mod.id])
            .map(mod => [mod.id, currentThumbnails[mod.id]]),
        )
        const installed = new Set(this.mods.map(mod => mod.id))
        this.replaceActiveIds(
          preserveDirty
            ? previousIds.filter(id => installed.has(id))
            : data.enabled_order,
        )
        this.reconcileInactiveOrder()
        this.missingEnabledIds = data.missing_enabled_ids
        this.orderToken = data.order_token
        this.warnings = data.warnings
        this.gameUpdatedAt = Number(data.game_updated_at || 0)
        this.modRevision = Number(data.mod_revision ?? this.modRevision)
        this.playsets = data.playsets || this.playsets
        this.currentPlaysetId = data.current_playset?.id || this.currentPlaysetId
        if (!this.selectedId || !installed.has(this.selectedId)) {
          this.selectedId = this.activeIds[0] || this.mods[0]?.id || ''
        }
        this.selectedIds = this.selectedIds.filter(id => installed.has(id))
        if (this.selectedId && !this.selectedIds.includes(this.selectedId)) this.selectedIds = [this.selectedId]
        if (!installed.has(this.selectionAnchorId)) this.selectionAnchorId = this.selectedId
        await this.loadPreview(this.selectedId)
        void this.loadThumbnails()
        this.notify(t('toast.scanComplete', { count: this.mods.length }))
        return data
      })
    },
    async refreshWorkshopInBackground() {
      if (this.workshopRefreshing || this.runtime.running) return
      await this.flushPlaysetUpdates()
      this.workshopRefreshing = true
      try {
        const data = await invoke('scan_mods', true)
        const installed = new Set(data.mods.map(mod => mod.id))
        const currentOrder = [...this.activeIds]
        this.mods = data.mods
        this.replaceActiveIds(
          this.dirty
            ? currentOrder.filter(id => installed.has(id))
            : data.enabled_order,
        )
        this.reconcileInactiveOrder()
        this.missingEnabledIds = data.missing_enabled_ids
        this.orderToken = data.order_token
        this.warnings = data.warnings
        this.gameUpdatedAt = Number(data.game_updated_at || 0)
        this.modRevision = Number(data.mod_revision ?? this.modRevision)
        this.playsets = data.playsets || this.playsets
        this.currentPlaysetId = data.current_playset?.id || this.currentPlaysetId
        if (!this.selectedId || !installed.has(this.selectedId)) {
          this.selectedId = this.activeIds[0] || this.mods[0]?.id || ''
        }
        this.selectedIds = this.selectedIds.filter(id => installed.has(id))
        if (this.selectedId && !this.selectedIds.includes(this.selectedId)) this.selectedIds = [this.selectedId]
        if (!installed.has(this.selectionAnchorId)) this.selectionAnchorId = this.selectedId
        await this.loadPreview(this.selectedId)
        void this.loadThumbnails(true)
        this.notify(t('toast.workshopComplete'))
      } catch (error) {
        this.notify(error.message || t('toast.workshopFailed'), 'warning')
      } finally {
        this.workshopRefreshing = false
      }
    },
    async loadThumbnails(force = false) {
      const installed = new Set(this.mods.map(mod => mod.id))
      const pending = this.mods
        .map(mod => mod.id)
        .filter(modId => force || !this.thumbnails[modId])
      for (let start = 0; start < pending.length; start += 80) {
        const chunk = pending.slice(start, start + 80)
        try {
          const data = await invoke('get_mod_thumbnails', chunk)
          const additions = Object.fromEntries(
            Object.entries(data.items || {}).filter(([modId, url]) => installed.has(modId) && url),
          )
          this.thumbnails = { ...this.thumbnails, ...additions }
        } catch {
          // Missing previews must not interrupt the rest of the list.
        }
      }
    },
    async selectMod(selection) {
      const payload = typeof selection === 'string' ? { id: selection } : (selection || {})
      const modId = String(payload.id || '')
      if (!modId || !this.modMap.has(modId)) return
      const orderedIds = Array.isArray(payload.orderedIds) ? payload.orderedIds : []
      const toggle = Boolean(payload.ctrlKey || payload.metaKey)
      const ranged = Boolean(payload.shiftKey)

      if (payload.preserveSelection && this.selectedIds.includes(modId)) {
        this.selectedId = modId
      } else if (ranged && orderedIds.includes(this.selectionAnchorId)) {
        const start = orderedIds.indexOf(this.selectionAnchorId)
        const end = orderedIds.indexOf(modId)
        const range = orderedIds.slice(Math.min(start, end), Math.max(start, end) + 1)
        this.selectedIds = toggle
          ? [...new Set([...this.selectedIds, ...range])]
          : range
        this.selectedId = modId
      } else if (toggle) {
        if (this.selectedIds.includes(modId)) {
          this.selectedIds = this.selectedIds.filter(id => id !== modId)
          this.selectedId = this.selectedIds.at(-1) || ''
        } else {
          this.selectedIds = [...this.selectedIds, modId]
          this.selectedId = modId
        }
        this.selectionAnchorId = modId
      } else {
        this.selectedIds = [modId]
        this.selectedId = modId
        this.selectionAnchorId = modId
      }
      await this.loadPreview(this.selectedId)
    },
    async selectAllMods(orderedIds) {
      const available = new Set(this.mods.map(mod => mod.id))
      const selected = [...new Set((orderedIds || []).map(String))]
        .filter(id => available.has(id))
      if (!selected.length) return []
      this.selectedIds = selected
      this.selectedId = selected[0]
      this.selectionAnchorId = selected[0]
      await this.loadPreview(this.selectedId)
      return selected
    },
    async loadPreview(modId) {
      this.selectedPreview = ''
      if (!modId) return
      try {
        const data = await invoke('get_mod_preview', modId)
        if (this.selectedId === modId) this.selectedPreview = data.url || ''
      } catch {
        this.selectedPreview = ''
      }
    },
    playsetOrderSnapshot() {
      const pending = new Set(this.missingEnabledIds)
      const previous = this.currentPlayset?.mod_ids || []
      const activeQueue = [...this.activeIds]
      const result = []
      for (const previousId of previous) {
        if (pending.has(previousId)) {
          result.push(previousId)
          pending.delete(previousId)
        } else if (activeQueue.length) {
          result.push(activeQueue.shift())
        }
      }
      result.push(...activeQueue, ...pending)
      return [...new Set(result.filter(Boolean))]
    },
    applyPlaysetPayload(data, replaceOrder = true) {
      this.playsets = data.playsets || this.playsets
      this.currentPlaysetId = data.current_playset?.id || this.currentPlaysetId
      if (Object.prototype.hasOwnProperty.call(data, 'missing_dependency_warnings')) {
        this.applyMissingDependencyWarnings(data.missing_dependency_warnings)
      }
      if (replaceOrder) {
        this.replaceActiveIds(data.ordered_mod_ids || [])
        this.missingEnabledIds = [...(data.missing_mod_ids || [])]
      }
    },
    recordCurrentPlaysetChange() {
      this.refreshMissingDependencyWarnings()
      const playsetId = this.currentPlaysetId
      const snapshot = this.playsetOrderSnapshot()
      const activeSnapshot = [...this.activeIds]
      if (!playsetId) return Promise.resolve()
      this.orderSavePending += 1
      this.orderSaving = true
      this.orderSaveError = ''
      const pending = enqueuePlaysetWrite(async () => {
        let succeeded = false
        try {
          const data = await invoke('update_playset', playsetId, snapshot)
          if (this.currentPlaysetId === playsetId) {
            this.playsets = data.playsets || this.playsets
            if (Object.prototype.hasOwnProperty.call(data, 'missing_dependency_warnings')) {
              this.applyMissingDependencyWarnings(data.missing_dependency_warnings)
            }
          }
          const saved = await invoke('save_load_order', activeSnapshot, this.orderToken)
          this.orderToken = saved.order_token
          if (saved.backup) this.backups.unshift(saved.backup)
          succeeded = true
          return data
        } finally {
          this.orderSavePending = Math.max(0, this.orderSavePending - 1)
          this.orderSaving = this.orderSavePending > 0
          if (succeeded && this.orderSavePending === 0) {
            this.dirty = false
            this.orderSaveError = ''
          }
        }
      })
      void pending.catch(error => {
        this.dirty = true
        this.orderSaveError = error.message || String(error)
        this.notify(t('toast.playsetSaveFailed', { error: error.message || String(error) }), 'error')
      })
      return pending
    },
    async flushPlaysetUpdates() {
      try {
        await playsetWriteQueue
      } catch {
        // The failed write has already been surfaced by recordCurrentPlaysetChange.
      }
    },
    async createPlayset(name) {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.createPlayset'), async () => {
        const data = await invoke('create_playset', name, this.playsetOrderSnapshot())
        this.applyPlaysetPayload(data)
        this.notify(t('toast.playsetCreated', { name: localizedPlaysetName(data.current_playset) }))
        return data.current_playset
      })
    },
    async renameCurrentPlayset(name) {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.renamePlayset'), async () => {
        const data = await invoke('rename_playset', this.currentPlaysetId, name)
        this.playsets = data.playsets
        this.currentPlaysetId = data.current_playset.id
        this.notify(t('toast.playsetRenamed', { name: localizedPlaysetName(data.playset) }))
        return data.playset
      })
    },
    async deleteCurrentPlayset() {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.deletePlayset'), async () => {
        const data = await invoke('delete_playset', this.currentPlaysetId)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        this.notify(t('toast.playsetSwitched', { name: localizedPlaysetName(data.current_playset) }))
        return data.current_playset
      })
    },
    async switchPlayset(playsetId) {
      if (!playsetId || playsetId === this.currentPlaysetId) return this.currentPlayset
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.switchPlayset'), async () => {
        this.stopCollectionImportDownloadSync()
        const data = await invoke('switch_playset', playsetId)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        if (data.missing_mod_ids.length) {
          this.notify(t('toast.playsetMissing', { count: data.missing_mod_ids.length }), 'warning')
        } else {
          this.notify(t('toast.playsetSwitched', { name: localizedPlaysetName(data.current_playset) }))
        }
        return data.current_playset
      })
    },
    enable(modId) {
      this.enableMany([modId])
    },
    enableMany(modIds) {
      let next = [...this.activeIds]
      for (const modId of [...new Set(modIds || [])]) {
        if (this.modMap.has(modId) && !next.includes(modId)) {
          next = insertByDefaultLoadOrder(next, modId, this.modMap)
        }
      }
      if (next.length !== this.activeIds.length) {
        this.replaceActiveIds(next)
        this.dirty = true
        this.recordCurrentPlaysetChange()
      }
    },
    reconcileInactiveOrder() {
      const installed = this.mods.map(mod => mod.id)
      const installedSet = new Set(installed)
      this.inactiveOrderIds = [
        ...this.inactiveOrderIds.filter(id => installedSet.has(id)),
        ...installed.filter(id => !this.inactiveOrderIds.includes(id)),
      ]
    },
    alignInactiveOrderToVisible(visibleOrder) {
      this.reconcileInactiveOrder()
      const visible = (visibleOrder || []).filter(id => this.inactiveOrderIds.includes(id))
      if (!visible.length) return [...this.inactiveOrderIds]
      const visibleSet = new Set(visible)
      const queue = [...visible]
      return this.inactiveOrderIds.map(id => (
        visibleSet.has(id) ? queue.shift() : id
      ))
    },
    enableManyAt(modIds, targetId = '') {
      const moving = [...new Set(modIds || [])]
        .filter(id => this.modMap.has(id) && !this.activeIds.includes(id))
      if (!moving.length) return
      const next = [...this.activeIds]
      const targetIndex = targetId ? next.indexOf(targetId) : -1
      const insertionIndex = targetIndex >= 0 ? targetIndex : next.length
      next.splice(insertionIndex, 0, ...moving)
      this.replaceActiveIds(next)
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    disable(modId) {
      this.disableMany([modId])
    },
    disableMany(modIds) {
      const selected = new Set(modIds || [])
      const next = this.activeIds.filter(id => !selected.has(id))
      if (next.length !== this.activeIds.length) {
        this.replaceActiveIds(next)
        this.dirty = true
        this.recordCurrentPlaysetChange()
      }
    },
    disableManyToInactive(modIds, targetId = '', targetOrder = []) {
      const selected = new Set(modIds || [])
      const moving = this.activeIds.filter(id => selected.has(id))
      if (!moving.length) return
      this.replaceActiveIds(this.activeIds.filter(id => !selected.has(id)))
      const base = this.alignInactiveOrderToVisible(targetOrder)
      const remaining = base.filter(id => !selected.has(id))
      const targetIndex = targetId ? remaining.indexOf(targetId) : -1
      const insertionIndex = targetIndex >= 0 ? targetIndex : remaining.length
      remaining.splice(insertionIndex, 0, ...moving)
      this.inactiveOrderIds = remaining
      this.inactiveOrderCustomized = true
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    reorder(sourceId, targetId) {
      this.reorderMany([sourceId], targetId, sourceId)
    },
    reorderMany(modIds, targetId, draggedId = '') {
      const selected = new Set(modIds || [])
      const moving = this.activeIds.filter(id => selected.has(id))
      if (!moving.length || (targetId && selected.has(targetId))) return
      const targetIndex = this.activeIds.indexOf(targetId)
      const anchorId = moving.includes(draggedId) ? draggedId : moving[0]
      const anchorIndex = this.activeIds.indexOf(anchorId)
      if (anchorIndex < 0 || (targetId && targetIndex < 0)) return
      const remaining = this.activeIds.filter(id => !selected.has(id))
      const remainingTargetIndex = targetId ? remaining.indexOf(targetId) : -1
      const insertionIndex = !targetId
        ? remaining.length
        : (anchorIndex < targetIndex ? remainingTargetIndex + 1 : remainingTargetIndex)
      const next = [
        ...remaining.slice(0, insertionIndex),
        ...moving,
        ...remaining.slice(insertionIndex),
      ]
      if (next.every((id, index) => id === this.activeIds[index])) return
      this.replaceActiveIds(next)
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    reorderInactiveMany(modIds, targetId, draggedId = '', visibleOrder = []) {
      const selected = new Set(modIds || [])
      if (targetId && selected.has(targetId)) return
      const base = this.alignInactiveOrderToVisible(visibleOrder)
      const moving = base.filter(id => selected.has(id))
      if (!moving.length) return
      const anchorId = moving.includes(draggedId) ? draggedId : moving[0]
      const anchorIndex = base.indexOf(anchorId)
      const targetIndex = targetId ? base.indexOf(targetId) : -1
      if (targetId && targetIndex < 0) return
      const remaining = base.filter(id => !selected.has(id))
      const remainingTargetIndex = targetId ? remaining.indexOf(targetId) : -1
      const insertionIndex = !targetId
        ? remaining.length
        : (anchorIndex < targetIndex ? remainingTargetIndex + 1 : remainingTargetIndex)
      const next = [
        ...remaining.slice(0, insertionIndex),
        ...moving,
        ...remaining.slice(insertionIndex),
      ]
      if (next.every((id, index) => id === this.inactiveOrderIds[index])) return
      this.inactiveOrderIds = next
      this.inactiveOrderCustomized = true
    },
    handleModDrop(payload) {
      const source = payload?.source
      const target = payload?.target
      const ids = payload?.ids || []
      if (!ids.length || !['active', 'inactive'].includes(source) || !['active', 'inactive'].includes(target)) return
      if (source === 'active' && target === 'active') {
        if (this.activeSortMode === 'priority') this.reorderMany(ids, payload.targetId, payload.draggedId)
      } else if (source === 'inactive' && target === 'inactive') {
        this.reorderInactiveMany(ids, payload.targetId, payload.draggedId, payload.targetOrder)
      } else if (source === 'inactive' && target === 'active') {
        this.enableManyAt(ids, payload.targetId)
      } else {
        this.disableManyToInactive(ids, payload.targetId, payload.targetOrder)
      }
    },
    move(modId, direction) {
      const index = this.activeIds.indexOf(modId)
      const target = index + direction
      if (index < 0 || target < 0 || target >= this.activeIds.length) return
      const next = [...this.activeIds]
      ;[next[index], next[target]] = [next[target], next[index]]
      this.replaceActiveIds(next)
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    moveToPosition(modId, oneBasedPosition) {
      const sourceIndex = this.activeIds.indexOf(modId)
      if (sourceIndex < 0 || this.activeIds.length === 0) return
      const numeric = Number(oneBasedPosition)
      if (!Number.isInteger(numeric)) return
      const targetIndex = Math.max(0, Math.min(numeric - 1, this.activeIds.length - 1))
      if (sourceIndex === targetIndex) return
      const next = [...this.activeIds]
      next.splice(sourceIndex, 1)
      next.splice(targetIndex, 0, modId)
      this.replaceActiveIds(next)
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    moveManyToPosition(modIds, oneBasedPosition) {
      const selected = new Set(modIds || [])
      const moving = this.activeIds.filter(id => selected.has(id))
      if (!moving.length) return
      const remaining = this.activeIds.filter(id => !selected.has(id))
      const numeric = Number(oneBasedPosition)
      if (!Number.isInteger(numeric)) return
      const targetIndex = Math.max(0, Math.min(numeric - 1, remaining.length))
      this.replaceActiveIds([
        ...remaining.slice(0, targetIndex),
        ...moving,
        ...remaining.slice(targetIndex),
      ])
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    applyLaunchResult(data) {
      this.orderToken = data.order_token
      this.dirty = false
      this.orderSaveError = ''
      this.runtime = { running: true }
      if (data.backup) this.backups.unshift(data.backup)
      return data
    },
    async launch() {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.launchGame'), async () => {
        const data = await invoke('launch_game', this.activeIds, this.orderToken)
        this.applyLaunchResult(data)
        this.notify(t('toast.gameLaunched', {
          game: localizedSelectedGameName(this.settings),
          pid: data.process.pid,
        }))
        return data
      })
    },
    async continueGame() {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.continueGame'), async () => {
        const data = await invoke('continue_game', this.activeIds, this.orderToken)
        this.applyLaunchResult(data)
        this.notify(t('toast.loadingSave', { name: data.save.name }))
        return data
      })
    },
    async loadSaveGames() {
      return this.withBusy(t('busy.readSaves'), async () => {
        const data = await invoke('list_save_games')
        this.saveGames = data.items || []
        this.saveGamesDirectory = data.directory || ''
        return data
      })
    },
    async readSaveMods(saveName) {
      return this.withBusy(t('busy.readSaveMods'), () => invoke('get_save_mods', saveName))
    },
    saveModLookup() {
      const byPackName = new Map()
      for (const mod of this.mods) {
        const key = String(mod.pack_name || '').toLocaleLowerCase()
        if (!key) continue
        const existing = byPackName.get(key)
        const sources = new Set(mod.sources?.length ? mod.sources : [mod.source])
        const existingSources = new Set(
          existing?.sources?.length ? existing.sources : [existing?.source],
        )
        if (
          !existing
          || (sources.has('data') && !existingSources.has('data'))
          || (sources.has('data') === existingSources.has('data') && mod.id < existing.id)
        ) {
          byPackName.set(key, mod)
        }
      }
      return byPackName
    },
    async compareSaveMods(saveName) {
      const data = await this.readSaveMods(saveName)
      const byPackName = this.saveModLookup()
      const saveKeys = new Set(data.pack_names.map(name => name.toLocaleLowerCase()))
      const active = this.activeIds.map(id => this.modMap.get(id)).filter(Boolean)
      const activeKeys = new Set(active.map(mod => mod.pack_name.toLocaleLowerCase()))
      const saveEntries = data.pack_names.map(packName => ({
        packName,
        mod: byPackName.get(packName.toLocaleLowerCase()) || null,
      }))
      return {
        save: data.save,
        saveOnly: saveEntries.filter(item => !activeKeys.has(item.packName.toLocaleLowerCase())),
        currentOnly: active
          .filter(mod => !saveKeys.has(mod.pack_name.toLocaleLowerCase()))
          .map(mod => ({ packName: mod.pack_name, mod })),
        shared: saveEntries.filter(item => activeKeys.has(item.packName.toLocaleLowerCase())),
      }
    },
    async createPlaysetFromSave(saveName) {
      const data = await this.readSaveMods(saveName)
      const byPackName = this.saveModLookup()
      const enabledIds = []
      const missingPackNames = []
      for (const packName of data.pack_names) {
        const mod = byPackName.get(packName.toLocaleLowerCase())
        if (mod) enabledIds.push(mod.id)
        else missingPackNames.push(packName)
      }
      const baseName = `存档${String(data.save?.name || saveName).trim()}`
      const existingNames = new Set(
        this.playsets.map(item => String(item.name || '').trim().toLocaleLowerCase()),
      )
      let playsetName = baseName
      let suffix = 2
      while (existingNames.has(playsetName.toLocaleLowerCase())) {
        playsetName = `${baseName} (${suffix})`
        suffix += 1
      }

      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.createPlayset'), async () => {
        const created = await invoke('create_playset', playsetName, enabledIds)
        this.applyPlaysetPayload(created)
        this.dirty = true
        await this.recordCurrentPlaysetChange()
        const playset = created.current_playset
        this.notify(
          missingPackNames.length
            ? t('toast.savePlaysetCreatedMissing', {
              name: localizedPlaysetName(playset),
              enabled: enabledIds.length,
              missing: missingPackNames.length,
            })
            : t('toast.savePlaysetCreated', {
              name: localizedPlaysetName(playset),
              count: enabledIds.length,
            }),
          missingPackNames.length ? 'warning' : 'success',
        )
        return { save: data.save, playset, enabledIds, missingPackNames }
      })
    },
    async launchSave(saveName) {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.loadSave'), async () => {
        const data = await invoke('launch_game', this.activeIds, this.orderToken, saveName)
        this.applyLaunchResult(data)
        this.notify(t('toast.loadingSave', { name: data.save.name }))
        return data
      })
    },
    async saveSettings(changes) {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.saveSettings'), async () => {
        const data = await invoke('save_settings', changes)
        this.settings = data.settings
        applyInterfaceLanguage(this.settings.language)
        this.paths = data.paths
        this.pathHealth = data.path_health
        this.mods = []
        this.thumbnails = {}
        this.replaceActiveIds([])
        this.inactiveOrderIds = []
        this.inactiveOrderCustomized = false
        this.selectedId = ''
        this.selectedIds = []
        this.selectionAnchorId = ''
        this.workshopEligibilityRequestId += 1
        this.workshopUpdateEligibility = new Set()
        this.dirty = false
        const changelog = await invoke('get_changelog')
        this.changelog = changelog.items || []
        this.notify(t('toast.settingsSaved'))
        return data
      })
    },
    async saveGameDataSettings(changes) {
      return this.withBusy(t('busy.saveGameData'), async () => {
        const data = await invoke('save_game_data_settings', changes)
        this.settings = data.settings
        this.notify(t('toast.gameDataSaved'))
        return data
      })
    },
    async checkForUpdates(manual = true) {
      if (this.updateChecking) return this.updateInfo
      this.updateChecking = true
      const execute = async () => {
        try {
          const data = await invoke('check_for_updates', manual)
          const localizedRelease = this.changelog.find(release => release.version === data.version)
          this.updateInfo = localizedRelease
            ? { ...data, entries: localizedRelease.entries || [] }
            : data
          if (data.checked_at) this.settings.last_update_check_at = data.checked_at
          this.autoUpdateDue = false
          if (manual && !data.has_update) this.notify(t('toast.latestVersion', { version: this.appVersion }))
          return data
        } catch (error) {
          if (!manual) {
            console.warn('Automatic update check failed', error)
            return null
          }
          throw error
        } finally {
          this.updateChecking = false
        }
      }
      if (manual) return this.withBusy(t('busy.checkUpdates'), execute)
      return execute()
    },
    async downloadUpdate() {
      const version = this.updateInfo?.version || ''
      return this.withBusy(t('busy.downloadUpdate'), async () => {
        const data = await invoke('download_update', version)
        this.updateInfo = data
        this.notify(t('toast.updateDownloaded', { version: data.version }))
        return data
      })
    },
    async installUpdate() {
      const version = this.updateInfo?.version || ''
      return this.withBusy(t('busy.installUpdate'), async () => {
        const data = await invoke('install_update', version)
        this.notify(t('toast.installingUpdate'))
        return data
      })
    },
    async ignoreUpdate() {
      const version = this.updateInfo?.version || ''
      if (!version) return null
      const data = await invoke('ignore_update', version)
      this.settings.ignored_update_version = data.ignored_update_version
      if (this.updateInfo) {
        this.updateInfo.ignored = true
        this.updateInfo.has_update = false
      }
      this.notify(t('toast.updateIgnored', { version }))
      return data
    },
    async refreshGameDataFeatures() {
      const data = await invoke('get_game_data_feature_status')
      const defaults = defaultGameDataFeatures()
      const received = data?.items || {}
      this.gameDataFeatures = Object.fromEntries(
        Object.entries(defaults).map(([key, fallback]) => [
          key,
          {
            ...fallback,
            ...(received[key] || {}),
            subscribed: Boolean(received[key]?.subscribed),
          },
        ]),
      )
      this.gameDataFeatureWarning = String(data?.warning || '')
      return data
    },
    async loadChangelog() {
      const data = await invoke('get_changelog')
      this.changelog = data.items || []
      return data
    },
    async acknowledgeChangelog() {
      const data = await invoke('acknowledge_changelog')
      this.settings.last_seen_app_version = data.last_seen_app_version
      return data
    },
    async detectPaths(gameId = '') {
      return this.withBusy(t('busy.detectSteam'), async () => {
        const data = await invoke('detect_paths', gameId)
        this.settings = data.settings
        applyInterfaceLanguage(this.settings.language)
        this.paths = data.paths
        this.pathHealth = data.path_health || {}
        this.workshopEligibilityRequestId += 1
        this.workshopUpdateEligibility = new Set()
        if (data.found) this.notify(t('toast.pathsDetected', {
          game: localizedSelectedGameName(this.settings),
        }))
        return data
      })
    },
    async selectDirectory(kind) {
      return invoke('select_directory', kind)
    },
    async saveModUserData(modId, alias, notes) {
      const updated = await invoke('save_mod_user_data', modId, alias, notes)
      const index = this.mods.findIndex(mod => mod.id === modId)
      if (index >= 0) this.mods[index] = updated
      this.notify(t('toast.modInfoSaved'))
    },
    async generateModUserData(modId) {
      return this.withBusy(t('busy.aiGenerate'), () => this.generateModUserDataDirect(modId))
    },
    async generateModUserDataDirect(modId) {
      const updated = await invoke('generate_mod_user_data', modId)
      const index = this.mods.findIndex(mod => mod.id === updated.id)
      if (index >= 0) this.mods[index] = updated
      this.notify(t('toast.aiSaved'))
      return updated
    },
    async generateModUserDataMany(modIds) {
      const ids = [...new Set((Array.isArray(modIds) ? modIds : [])
        .map(id => String(id || '').trim())
        .filter(Boolean))]
      return this.withBusy(t('busy.aiGenerate'), async () => {
        const succeeded = []
        const failed = []
        for (const modId of ids) {
          try {
            await this.generateModUserDataDirect(modId)
            succeeded.push(modId)
          } catch (error) {
            failed.push(modId)
            this.notify(error.message || String(error), 'error')
          }
        }
        return { succeeded, failed }
      })
    },
    setActiveSearchTokens(tokens) {
      this.activeSearchTokens = Array.isArray(tokens) ? tokens : []
    },
    setActiveSearchLogic(logic) {
      this.activeSearchLogic = logic === 'OR' ? 'OR' : 'AND'
    },
    setInactiveSearchTokens(tokens) {
      this.inactiveSearchTokens = Array.isArray(tokens) ? tokens : []
    },
    setInactiveSearchLogic(logic) {
      this.inactiveSearchLogic = logic === 'OR' ? 'OR' : 'AND'
    },
    async setActiveSearchHighlightMode(enabled) {
      return this.withBusy(t('busy.saveSettings'), async () => {
        const data = await invoke('set_search_highlight_mode', Boolean(enabled), 'active')
        this.settings = data.settings
        return data
      })
    },
    async setInactiveSearchHighlightMode(enabled) {
      return this.withBusy(t('busy.saveSettings'), async () => {
        const data = await invoke('set_search_highlight_mode', Boolean(enabled), 'inactive')
        this.settings = data.settings
        return data
      })
    },
    setActiveSortMode(mode) {
      if (!SORT_OPTIONS.some(option => option.id === mode)) return
      this.activeSortMode = mode
      this.activeSortDescending = mode === 'updated' || mode === 'created' || mode === 'subscription'
    },
    setActiveSortDescending(descending) {
      this.activeSortDescending = Boolean(descending)
    },
    setInactiveSortMode(mode) {
      if (!SORT_OPTIONS.some(option => option.id === mode)) return
      this.inactiveSortMode = mode
      this.inactiveSortDescending = mode === 'updated' || mode === 'created' || mode === 'subscription'
      this.inactiveOrderCustomized = false
    },
    setInactiveSortDescending(descending) {
      this.inactiveSortDescending = Boolean(descending)
    },
    async reorderModTypes(typeIds) {
      return this.withBusy(t('busy.editType'), async () => {
        const data = await invoke('reorder_mod_types', typeIds)
        this.modTypes = data.items || []
        return this.modTypes
      })
    },
    async setModType(modId, typeId) {
      return this.withBusy(t('busy.editType'), async () => {
        const updated = await invoke('set_mod_types', modId, [typeId])
        const index = this.mods.findIndex(mod => mod.id === updated.id)
        if (index >= 0) this.mods[index] = updated
        this.notify(t('toast.typeChanged', { name: this.modTypeMap[typeId] || t('common.unknown') }))
        return updated
      })
    },
    async toggleModType(modId, typeId) {
      const mod = this.modMap.get(modId)
      if (!mod) throw new Error(t('toast.modMissing'))
      const current = [...new Set(mod.mod_types?.length ? mod.mod_types : [mod.mod_type || 'unknown'])]
      let next
      if (typeId === 'unknown') {
        next = ['unknown']
      } else if (current.includes(typeId)) {
        next = current.filter(item => item !== typeId && item !== 'unknown')
        if (!next.length) next = ['unknown']
      } else {
        next = [...current.filter(item => item !== 'unknown'), typeId]
      }
      return this.withBusy(t('busy.editType'), async () => {
        const updated = await invoke('set_mod_types', modId, next)
        const index = this.mods.findIndex(item => item.id === updated.id)
        if (index >= 0) this.mods[index] = updated
        const names = updated.mod_types.map(item => this.modTypeMap[item] || item).join(', ')
        this.notify(t('toast.typeSet', { names }))
        return updated
      })
    },
    async setModHidden(modId, hidden) {
      return this.withBusy(hidden ? t('busy.hideMod') : t('busy.unhideMod'), async () => {
        const updated = await invoke('set_mod_hidden', modId, hidden)
        const index = this.mods.findIndex(mod => mod.id === updated.id)
        if (index >= 0) this.mods[index] = updated
        if (hidden && !this.showHidden && this.selectedId === updated.id) {
          const next = [...this.activeMods, ...this.inactiveMods][0]
          this.selectedId = next?.id || ''
          this.selectedIds = this.selectedId ? [this.selectedId] : []
          this.selectionAnchorId = this.selectedId
          await this.loadPreview(this.selectedId)
        }
        this.notify(hidden ? t('toast.hidden') : t('toast.unhidden'))
        return updated
      })
    },
    async createModType(name) {
      return this.withBusy(t('busy.createType'), async () => {
        const data = await invoke('create_mod_type', name)
        this.modTypes = data.items
        this.notify(t('toast.typeCreated', { name: data.item.name }))
        return data.item
      })
    },
    async updateModType(typeId, name) {
      return this.withBusy(t('busy.editType'), async () => {
        const data = await invoke('update_mod_type', typeId, name)
        this.modTypes = data.items
        this.notify(t('toast.typeChanged', { name: data.item.name }))
        return data.item
      })
    },
    async deleteModType(typeId) {
      return this.withBusy(t('busy.deleteType'), async () => {
        const data = await invoke('delete_mod_type', typeId)
        this.modTypes = data.items
        this.mods = this.mods.map(mod => {
          const selected = (mod.mod_types?.length ? mod.mod_types : [mod.mod_type || 'unknown'])
            .filter(item => item !== typeId)
          const modTypes = selected.length ? selected : ['unknown']
          return { ...mod, mod_type: modTypes[0], mod_types: modTypes }
        })
        this.notify(t('toast.typeDeleted'))
      })
    },
    async exportShare() {
      return invoke('export_share', this.activeIds)
    },
    async previewShareImport(value) {
      return this.withBusy(t('busy.previewShare'), () => invoke('preview_import_share', value))
    },
    async subscribeWorkshopItems(workshopIds) {
      return this.withBusy(t('busy.subscribeWorkshop'), async () => {
        const data = await invoke('subscribe_workshop_items', workshopIds)
        const subscribed = data.subscribed?.length || 0
        const existing = data.already_subscribed?.length || 0
        this.notify(t('toast.subscriptionAccepted', {
          subscribed,
          existing: existing ? t('toast.subscriptionExisting', { count: existing }) : '',
        }))
        return data
      })
    },
    async subscribeAndEnableMissingDependencies(items) {
      const dependencies = (Array.isArray(items) ? items : [])
        .filter(item => item?.code === 'missing_dependency')
        .flatMap(item => Array.isArray(item.dependencies) ? item.dependencies : [])
      const installedIds = []
      const workshopIds = []
      const pendingIds = []
      const seen = new Set()
      for (const dependency of dependencies) {
        const kind = String(dependency?.kind || '')
        const dependencyId = String(dependency?.id || '').trim()
        if (!dependencyId) continue
        const key = `${kind}:${dependencyId.toLocaleLowerCase()}`
        if (seen.has(key)) continue
        seen.add(key)
        const mod = kind === 'workshop'
          ? this.mods.find(item => String(item.workshop_id || '') === dependencyId)
          : this.mods.find(item => String(item.pack_name || '').toLocaleLowerCase() === dependencyId.toLocaleLowerCase())
        if (mod) {
          installedIds.push(mod.id)
        } else if (kind === 'workshop' && /^\d+$/.test(dependencyId)) {
          workshopIds.push(dependencyId)
          pendingIds.push(`pending:steam:${dependencyId}:`)
        }
      }
      if (!installedIds.length && !workshopIds.length) return { enabled: [], subscribed: [], pending: [] }
      return this.withBusy(t('busy.subscribeWorkshop'), async () => {
        let subscription = { subscribed: [], already_subscribed: [] }
        if (workshopIds.length) subscription = await invoke('subscribe_workshop_items', workshopIds)
        const nextActive = [...this.activeIds]
        for (const modId of installedIds) {
          if (this.modMap.has(modId) && !nextActive.includes(modId)) {
            nextActive.splice(0, nextActive.length, ...insertByDefaultLoadOrder(nextActive, modId, this.modMap))
          }
        }
        const activeChanged = nextActive.length !== this.activeIds.length
        const nextPending = [...new Set([...(this.missingEnabledIds || []), ...pendingIds])]
        const pendingChanged = nextPending.length !== (this.missingEnabledIds || []).length
        if (activeChanged) this.replaceActiveIds(nextActive)
        if (pendingChanged) this.missingEnabledIds = nextPending
        if (activeChanged || pendingChanged) {
          this.dirty = true
          await this.recordCurrentPlaysetChange()
        }
        const subscribed = subscription.subscribed?.length || 0
        const existing = subscription.already_subscribed?.length || 0
        this.notify(t('toast.missingDependenciesEnabled', {
          enabled: installedIds.length,
          pending: workshopIds.length,
          subscribed,
          existing: existing ? t('toast.subscriptionExisting', { count: existing }) : '',
        }), pendingIds.length ? 'warning' : 'success')
        return {
          enabled: installedIds,
          pending: pendingIds,
          subscribed: subscription.subscribed || [],
          alreadySubscribed: subscription.already_subscribed || [],
        }
      })
    },
    async importShare(value) {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.importShare'), async () => {
        const data = await invoke('import_share', value)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        if ((data.pending_workshop_ids || []).length) {
          this.notify(
            t('toast.pendingDownloads', { count: data.pending_workshop_ids.length }),
            'warning',
          )
        } else if ((data.missing || []).length) {
          this.notify(t('toast.localMissing', { count: data.missing.length }), 'warning')
        } else {
          this.notify(t('toast.playsetUpdated', { name: localizedPlaysetName(data.current_playset) }))
        }
        return data
      })
    },
    async importWorkshopCollection(value) {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.importWorkshopCollection'), async () => {
        const data = await invoke('import_workshop_collection', value)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        const subscribed = data.subscribed_workshop_ids?.length || 0
        if (subscribed) {
          this.notify(t('toast.subscriptionAccepted', {
            subscribed,
            existing: '',
          }))
        }
        const subscriptionFailures = data.subscription_failures?.length || 0
        if (subscriptionFailures) {
          this.notify(
            t('toast.collectionSubscriptionPartial', { count: subscriptionFailures }),
            'warning',
          )
        }
        if ((data.pending_workshop_ids || []).length) {
          this.startCollectionImportDownloadSync(
            data.pending_workshop_ids,
            data.subscription_failures,
          )
          this.notify(
            t('toast.pendingDownloads', { count: data.pending_workshop_ids.length }),
            'warning',
          )
        } else {
          this.notify(t('toast.playsetUpdated', { name: localizedPlaysetName(data.current_playset) }))
        }
        return data
      })
    },
    async selectOfficialProfile() {
      return invoke('select_mod_profile')
    },
    async previewOfficialProfile(path) {
      return this.withBusy(
        t('busy.previewOfficialProfile'),
        () => invoke('preview_mod_profile', path),
      )
    },
    async importOfficialProfile(path, mode) {
      await this.flushPlaysetUpdates()
      return this.withBusy(t('busy.importOfficialProfile'), async () => {
        const data = await invoke('import_mod_profile', path, mode)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        this.notify(
          (data.pending_workshop_ids || []).length
            ? t('toast.officialPending', { count: data.pending_workshop_ids.length })
            : t('toast.officialImported', { name: localizedPlaysetName(data.current_playset) }),
          (data.pending_workshop_ids || []).length ? 'warning' : 'success',
        )
        return data
      })
    },
    async openModFolder(modId) {
      await invoke('open_mod_folder', modId)
    },
    async copyModPaths(modIds) {
      const paths = []
      const seen = new Set()
      for (const modId of modIds || []) {
        const path = String(this.modMap.get(modId)?.path || '')
        const key = path.toLocaleLowerCase()
        if (!path || seen.has(key)) continue
        seen.add(key)
        paths.push(path)
      }
      if (!paths.length) return []
      await navigator.clipboard.writeText(paths.join('\n'))
      this.notify(t('toast.modPathsCopied', { count: paths.length }))
      return paths
    },
    async previewDeleteModFiles(modIds) {
      return this.withBusy(
        t('busy.previewDeleteMods'),
        () => invoke('preview_delete_mod_files', modIds),
      )
    },
    startCollectionImportDownloadSync(pendingWorkshopIds, subscriptionFailures = []) {
      const failedIds = new Set(
        (subscriptionFailures || [])
          .map(item => String(item?.workshop_id || ''))
          .filter(value => /^\d+$/.test(value)),
      )
      const pendingIds = [...new Set((pendingWorkshopIds || []).map(String))]
        .filter(value => /^\d+$/.test(value) && !failedIds.has(value))
      if (!pendingIds.length) return
      this.collectionImportSync = {
        playsetId: this.currentPlaysetId,
        pendingWorkshopIds: pendingIds,
      }
      this.scheduleCollectionImportDownloadRefresh()
    },
    stopCollectionImportDownloadSync() {
      this.collectionImportSync = null
      if (collectionImportPollTimer) {
        window.clearTimeout(collectionImportPollTimer)
        collectionImportPollTimer = 0
      }
    },
    scheduleCollectionImportDownloadRefresh() {
      if (collectionImportPollTimer || !this.collectionImportSync) return
      collectionImportPollTimer = window.setTimeout(async () => {
        collectionImportPollTimer = 0
        await this.refreshCollectionImportDownloads()
      }, COLLECTION_IMPORT_POLL_INTERVAL_MS)
    },
    updateCollectionImportProgress(data) {
      const sync = this.collectionImportSync
      if (!sync || sync.playsetId !== this.currentPlaysetId) return
      const pendingIds = new Set(
        (data.missing_enabled_ids || []).map(pendingWorkshopId).filter(Boolean),
      )
      const remaining = sync.pendingWorkshopIds.filter(id => pendingIds.has(id))
      this.collectionImportSync = remaining.length
        ? { ...sync, pendingWorkshopIds: remaining }
        : null
    },
    async refreshCollectionImportDownloads() {
      const sync = this.collectionImportSync
      if (!sync) return null
      if (sync.playsetId !== this.currentPlaysetId || this.runtime.running) {
        this.stopCollectionImportDownloadSync()
        return null
      }
      if (this.liveModRefreshing || this.workshopRefreshing || this.busy) {
        this.scheduleCollectionImportDownloadRefresh()
        return null
      }
      this.liveModRefreshing = true
      try {
        await this.flushPlaysetUpdates()
        const previousActiveIds = [...this.activeIds]
        const data = await invoke('scan_mods', false)
        await this.applyExternalScan(data, { forcePlaysetOrder: true })
        this.updateCollectionImportProgress(data)
        if (!sameIds(previousActiveIds, this.activeIds)) {
          this.dirty = true
          this.recordCurrentPlaysetChange()
        }
        return data
      } catch {
        return null
      } finally {
        this.liveModRefreshing = false
        this.scheduleCollectionImportDownloadRefresh()
      }
    },
    async applyExternalScan(data, { forcePlaysetOrder = false } = {}) {
      if (!data) return
      const previousIds = [...this.activeIds]
      const installed = new Set((data.mods || []).map(mod => mod.id))
      this.mods = data.mods || []
      this.replaceActiveIds(
        this.dirty && !forcePlaysetOrder
          ? previousIds.filter(id => installed.has(id))
          : (data.enabled_order || []),
      )
      this.reconcileInactiveOrder()
      this.missingEnabledIds = data.missing_enabled_ids || []
      this.orderToken = data.order_token || this.orderToken
      this.warnings = data.warnings || []
      this.gameUpdatedAt = Number(data.game_updated_at || 0)
      this.modRevision = Number(data.mod_revision ?? this.modRevision)
      this.playsets = data.playsets || this.playsets
      this.currentPlaysetId = data.current_playset?.id || this.currentPlaysetId
      if (!installed.has(this.selectedId)) this.selectedId = this.activeIds[0] || this.mods[0]?.id || ''
      this.selectedIds = this.selectedIds.filter(id => installed.has(id))
      if (this.selectedId && !this.selectedIds.includes(this.selectedId)) this.selectedIds = [this.selectedId]
      this.selectionAnchorId = installed.has(this.selectionAnchorId) ? this.selectionAnchorId : this.selectedId
      await this.loadPreview(this.selectedId)
      void this.loadThumbnails()
    },
    async refreshModsInBackground() {
      if (this.liveModRefreshing || this.workshopRefreshing || this.runtime.running || this.busy) return null
      this.liveModRefreshing = true
      try {
        await this.flushPlaysetUpdates()
        const previousWorkshopIds = new Set(
          this.mods
            .map(mod => String(mod?.workshop_id || '').trim())
            .filter(Boolean),
        )
        let data = await invoke('scan_mods', false)
        const hasNewWorkshopMod = (data.mods || []).some(mod => {
          const workshopId = String(mod?.workshop_id || '').trim()
          return mod?.source === 'workshop' && workshopId && !previousWorkshopIds.has(workshopId)
        })
        if (hasNewWorkshopMod && this.settings.fetch_workshop_metadata !== false) {
          data = await invoke('scan_mods', true)
        }
        const forcePlaysetOrder = this.collectionImportSync?.playsetId === this.currentPlaysetId
        const previousActiveIds = [...this.activeIds]
        await this.applyExternalScan(data, { forcePlaysetOrder })
        if (forcePlaysetOrder) {
          this.updateCollectionImportProgress(data)
          if (!sameIds(previousActiveIds, this.activeIds)) {
            this.dirty = true
            this.recordCurrentPlaysetChange()
          }
        }
        return data
      } catch (error) {
        this.notify(error.message || t('toast.liveModRefreshFailed'), 'warning')
        return null
      } finally {
        this.liveModRefreshing = false
      }
    },
    async deleteModFiles(previewToken) {
      const data = await this.withBusy(
        t('busy.deleteMods'),
        () => invoke('delete_mod_files', previewToken),
      )
      await this.applyExternalScan(data.scan)
      this.notify(
        data.failed_count
          ? t('toast.modsDeletedPartial', { deleted: data.deleted_count, failed: data.failed_count })
          : t('toast.modsDeleted', { count: data.deleted_count }),
        data.failed_count ? 'warning' : 'success',
      )
      return data
    },
    async setModWarningIgnored(modId, warningCode, ignored) {
      return this.withBusy(ignored ? t('busy.ignoreIssue') : t('busy.restoreIssue'), async () => {
        const updated = await invoke('set_mod_warning_ignored', modId, warningCode, ignored)
        const index = this.mods.findIndex(mod => mod.id === updated.id)
        if (index >= 0) this.mods[index] = updated
        this.refreshMissingDependencyWarnings()
        return updated
      })
    },
    ignoreScanWarning(warningCode) {
      const normalized = String(warningCode || '').trim()
      if (!normalized || this.ignoredScanWarningCodes.includes(normalized)) return
      this.ignoredScanWarningCodes = [...this.ignoredScanWarningCodes, normalized]
    },
    async openWorkshopFolder(modId) {
      await invoke('open_workshop_folder', modId)
    },
    async openWorkshop(modId) {
      await invoke('open_workshop_page', modId)
    },
    async openWorkshopClient(modId) {
      await invoke('open_workshop_client', modId)
    },
    async openExternalUrl(url) {
      return invoke('open_external_url', url)
    },
    async unsubscribeWorkshop(modId) {
      return this.unsubscribeWorkshopMany([modId])
    },
    async unsubscribeWorkshopMany(modIds) {
      const data = await this.withBusy(
        t('busy.unsubscribeWorkshop'),
        () => invoke('unsubscribe_workshop_mods', modIds),
      )
      await this.applyExternalScan(data.scan)
      this.notify(
        data.failed_count
          ? t('toast.unsubscribePartial', { completed: data.completed_count, failed: data.failed_count })
          : t('toast.unsubscribeRemoved', { count: data.completed_count }),
        data.failed_count ? 'warning' : 'success',
      )
      return data
    },
    async forceUpdateWorkshop(modId) {
      return this.withBusy(t('busy.forceUpdateWorkshop'), async () => {
        const data = await invoke('force_update_workshop_mod', modId)
        this.notify(t('toast.forceUpdateCompleted'))
        return data
      })
    },
    async refreshWorkshopUpdateEligibility(modIds) {
      const requestId = ++this.workshopEligibilityRequestId
      this.workshopUpdateEligibility = new Set()
      const requestedIds = [...new Set(
        (Array.isArray(modIds) ? modIds : [])
          .map(id => String(id || '').trim())
          .filter(Boolean),
      )]
      if (!requestedIds.length) return []
      try {
        const data = await invoke('get_workshop_update_eligibility', requestedIds)
        if (requestId !== this.workshopEligibilityRequestId) return []
        const eligible = Array.isArray(data?.eligible_mod_ids) ? data.eligible_mod_ids : []
        this.workshopUpdateEligibility = new Set(eligible.map(id => String(id)))
        return eligible
      } catch {
        if (requestId === this.workshopEligibilityRequestId) {
          this.workshopUpdateEligibility = new Set()
        }
        return []
      }
    },
    async loadWorkshopPublishCopy(modId, language) {
      try {
        return await invoke('get_workshop_publish_copy', modId, language)
      } catch (error) {
        this.notify(error.message || t('toast.publishCopyFailed'), 'error')
        throw error
      }
    },
    async publishWorkshopItem(modId, publishData) {
      const mode = publishData?.mode === 'update' ? 'update' : 'upload'
      return this.withBusy(mode === 'upload' ? t('busy.uploadWorkshop') : t('busy.updateWorkshop'), async () => {
        const data = await invoke('publish_workshop_item', modId, publishData)
        const index = this.mods.findIndex(mod => mod.id === data.mod.id)
        if (index >= 0) this.mods[index] = data.mod
        const agreementNote = data.result.needs_to_accept_agreement ? t('toast.agreementNeeded') : ''
        this.notify(t(mode === 'upload' ? 'toast.workshopUploaded' : 'toast.workshopUpdated', {
          id: data.result.workshop_id,
          agreement: agreementNote,
        }))
        return data
      })
    },
    async openModInRpfm(modId) {
      return this.withBusy(t('busy.startRpfm'), async () => {
        const data = await invoke('open_mod_in_rpfm', modId)
        this.notify(t('toast.rpfmOpened'))
        return data
      })
    },
    async copyModToData(modId) {
      const source = this.modMap.get(modId)
      const packName = source?.pack_name || ''
      const activeIndex = this.activeIds.indexOf(modId)
      const wasDirty = this.dirty
      const data = await this.withBusy(t('busy.copyData'), () => invoke('copy_mod_to_data', modId))
      if (!data.copied) {
        this.notify(t('toast.alreadyData'), 'warning')
        return data
      }
      await this.scan(false)
      const replacement = this.mods.find(mod => mod.pack_name.toLocaleLowerCase() === packName.toLocaleLowerCase())
      if (activeIndex >= 0 && replacement && !this.activeIds.includes(replacement.id)) {
        const next = [...this.activeIds]
        next.splice(Math.min(activeIndex, next.length), 0, replacement.id)
        this.replaceActiveIds(next)
        this.dirty = wasDirty
        this.recordCurrentPlaysetChange()
      }
      if (replacement) await this.selectMod(replacement.id)
      this.notify(t('toast.copiedData', { name: packName }))
      return data
    },
    async syncWorkshopToData() {
      const activePackNames = this.activeIds
        .map(id => this.modMap.get(id)?.pack_name)
        .filter(Boolean)
      const selectedPackName = this.selectedMod?.pack_name || ''
      const wasDirty = this.dirty
      const data = await this.withBusy(
        t('busy.syncData'),
        () => invoke('sync_workshop_to_data'),
      )
      if (data.copied || data.updated) {
        await this.scan(false)
        const byPackName = new Map(this.mods.map(mod => [mod.pack_name.toLocaleLowerCase(), mod.id]))
        this.replaceActiveIds([...new Set(
          activePackNames
            .map(name => byPackName.get(name.toLocaleLowerCase()))
            .filter(Boolean),
        )])
        this.dirty = wasDirty
        this.recordCurrentPlaysetChange()
        if (selectedPackName) {
          const replacement = byPackName.get(selectedPackName.toLocaleLowerCase())
          if (replacement) await this.selectMod(replacement)
        }
      }
      const skipped = Number(data.skipped || 0)
      this.notify(
        t('toast.syncComplete', {
          copied: data.copied,
          updated: data.updated,
          unchanged: data.unchanged,
          skipped: skipped ? t('toast.syncSkipped', { count: skipped }) : '',
        }),
        skipped && !data.copied && !data.updated ? 'warning' : 'success',
      )
      return data
    },
    async openGameFolder() {
      await invoke('open_game_folder')
    },
    async refreshRuntime() {
      try {
        const previousRevision = this.modRevision
        const runtime = await invoke('get_runtime_status')
        this.runtime = runtime
        const nextRevision = Number(runtime.mod_revision || 0)
        if (
          this.settings.live_mod_detection
          && !runtime.running
          && nextRevision > previousRevision
        ) {
          const refreshed = await this.refreshModsInBackground()
          if (!refreshed) this.modRevision = previousRevision
        } else {
          this.modRevision = nextRevision
        }
      } catch {
        // Runtime polling must never interrupt the main workflow.
      }
    },
  },
})
