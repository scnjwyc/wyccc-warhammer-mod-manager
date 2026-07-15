import { defineStore } from 'pinia'
import { invoke } from './bridge'
import { applyInterfaceLanguage } from './languages'
import {
  insertByDefaultLoadOrder,
  matchesSearchTokens,
  SORT_OPTIONS,
  sortDisplayedMods,
} from './modSearch'

let playsetWriteQueue = Promise.resolve()

const enqueuePlaysetWrite = task => {
  const pending = playsetWriteQueue.catch(() => {}).then(task)
  playsetWriteQueue = pending
  return pending
}

export const useAppStore = defineStore('app', {
  state: () => ({
    appName: "Wyccc's Mod Manager",
    appVersion: '0.1.0',
    settings: {},
    paths: {},
    pathHealth: {},
    mods: [],
    modTypes: [],
    showHidden: false,
    activeIds: [],
    selectedId: '',
    selectedIds: [],
    selectionAnchorId: '',
    selectedPreview: '',
    thumbnails: {},
    searchTokens: [],
    searchLogic: 'AND',
    sortMode: 'priority',
    sortDescending: false,
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
    warnings: [],
    gameUpdatedAt: 0,
    missingEnabledIds: [],
    runtime: { running: false },
    saveGames: [],
    saveGamesDirectory: '',
    changelog: [],
    updateInfo: null,
    updateChecking: false,
    autoUpdateDue: false,
    toast: null,
  }),
  getters: {
    modMap: (state) => new Map(state.mods.map(mod => [mod.id, mod])),
    modTypeMap: (state) => Object.fromEntries(state.modTypes.map(item => [item.id, item.name])),
    hiddenCount: (state) => state.mods.filter(mod => mod.hidden).length,
    warningItems(state) {
      const items = state.warnings.map((message, index) => ({
        id: `scan:${index}`,
        message,
        severity: 'warning',
        modId: '',
        modName: '',
      }))
      for (const mod of state.mods) {
        for (const [index, warning] of (mod.warnings || []).entries()) {
          items.push({
            id: `${mod.id}:${warning.code || index}`,
            message: warning.message || String(warning),
            severity: warning.severity || 'warning',
            modId: mod.id,
            modName: mod.effective_name || mod.display_name || mod.pack_name,
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
    activeMods() {
      const mods = this.activeIds
        .map(id => this.modMap.get(id))
        .filter(Boolean)
        .filter(mod => this.showHidden || !mod.hidden)
        .filter(mod => matchesSearchTokens(mod, this.searchTokens, this.searchLogic, this.modTypeMap))
      return sortDisplayedMods(mods, this.sortMode, this.sortDescending)
    },
    inactiveMods() {
      const active = new Set(this.activeIds)
      const mods = this.mods
        .filter(mod => !active.has(mod.id))
        .filter(mod => this.showHidden || !mod.hidden)
        .filter(mod => matchesSearchTokens(mod, this.searchTokens, this.searchLogic, this.modTypeMap))
      return sortDisplayedMods(mods, this.sortMode, this.sortDescending)
    },
  },
  actions: {
    notify(message, type = 'success') {
      this.toast = { message, type, id: Date.now() }
      window.setTimeout(() => {
        if (this.toast?.message === message) this.toast = null
      }, 3200)
    },
    async withBusy(label, task) {
      if (this.busy) throw new Error(`正在执行：${this.busy}`)
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
      const data = await this.withBusy('初始化', () => invoke('get_bootstrap'))
      this.appName = data.app_name
      this.appVersion = data.app_version
      this.settings = data.settings
      applyInterfaceLanguage(this.settings.language)
      this.paths = data.paths
      this.pathHealth = data.path_health
      this.activeIds = [...data.enabled_order]
      this.playsets = data.playsets || []
      this.currentPlaysetId = data.current_playset?.id || 'default'
      this.backups = data.backups
      this.modTypes = data.mod_types || []
      this.orderToken = data.order_token
      this.runtime = data.runtime
      this.changelog = data.changelog || []
      this.autoUpdateDue = Boolean(data.auto_update_due)
      if (this.pathHealth.game_ready) {
        await this.scan(false)
        if (this.settings.fetch_workshop_metadata) void this.refreshWorkshopInBackground()
      }
      if (data.update_install_error) {
        const installError = String(data.update_install_error).slice(-320)
        this.notify(`自动更新安装失败，已恢复旧版本：${installError}`, 'error')
      }
      return data
    },
    async scan(refreshWorkshop = false) {
      await this.flushPlaysetUpdates()
      return this.withBusy(refreshWorkshop ? '刷新工坊信息' : '扫描 MOD', async () => {
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
        this.activeIds = preserveDirty
          ? previousIds.filter(id => installed.has(id))
          : data.enabled_order
        this.missingEnabledIds = data.missing_enabled_ids
        this.orderToken = data.order_token
        this.warnings = data.warnings
        this.gameUpdatedAt = Number(data.game_updated_at || 0)
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
        this.notify(`扫描完成：${this.mods.length} 个 Pack`)
        return data
      })
    },
    async refreshWorkshopInBackground() {
      if (this.workshopRefreshing) return
      await this.flushPlaysetUpdates()
      this.workshopRefreshing = true
      try {
        const data = await invoke('scan_mods', true)
        const installed = new Set(data.mods.map(mod => mod.id))
        const currentOrder = [...this.activeIds]
        this.mods = data.mods
        this.activeIds = this.dirty
          ? currentOrder.filter(id => installed.has(id))
          : data.enabled_order
        this.missingEnabledIds = data.missing_enabled_ids
        this.orderToken = data.order_token
        this.warnings = data.warnings
        this.gameUpdatedAt = Number(data.game_updated_at || 0)
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
        this.notify('工坊信息已在后台刷新完成')
      } catch (error) {
        this.notify(error.message || '后台刷新工坊信息失败', 'warning')
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
      const active = new Set(this.activeIds)
      return [
        ...this.activeIds,
        ...this.missingEnabledIds.filter(id => !active.has(id)),
      ]
    },
    applyPlaysetPayload(data, replaceOrder = true) {
      this.playsets = data.playsets || this.playsets
      this.currentPlaysetId = data.current_playset?.id || this.currentPlaysetId
      if (replaceOrder) {
        this.activeIds = [...(data.ordered_mod_ids || [])]
        this.missingEnabledIds = [...(data.missing_mod_ids || [])]
      }
    },
    recordCurrentPlaysetChange() {
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
        this.notify(`保存当前播放集失败：${error.message || String(error)}`, 'error')
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
      return this.withBusy('新建播放集', async () => {
        const data = await invoke('create_playset', name, this.playsetOrderSnapshot())
        this.applyPlaysetPayload(data)
        this.notify(`已新建播放集“${data.current_playset.name}”`)
        return data.current_playset
      })
    },
    async renameCurrentPlayset(name) {
      await this.flushPlaysetUpdates()
      return this.withBusy('重命名播放集', async () => {
        const data = await invoke('rename_playset', this.currentPlaysetId, name)
        this.playsets = data.playsets
        this.currentPlaysetId = data.current_playset.id
        this.notify(`播放集已重命名为“${data.playset.name}”`)
        return data.playset
      })
    },
    async deleteCurrentPlayset() {
      await this.flushPlaysetUpdates()
      return this.withBusy('删除播放集', async () => {
        const data = await invoke('delete_playset', this.currentPlaysetId)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        this.notify(`已切换到播放集“${data.current_playset.name}”`)
        return data.current_playset
      })
    },
    async switchPlayset(playsetId) {
      if (!playsetId || playsetId === this.currentPlaysetId) return this.currentPlayset
      await this.flushPlaysetUpdates()
      return this.withBusy('切换播放集', async () => {
        const data = await invoke('switch_playset', playsetId)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        if (data.missing_mod_ids.length) {
          this.notify(`播放集中有 ${data.missing_mod_ids.length} 个 Pack 未安装`, 'warning')
        } else {
          this.notify(`已切换到播放集“${data.current_playset.name}”`)
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
        this.activeIds = next
        this.dirty = true
        this.recordCurrentPlaysetChange()
      }
    },
    disable(modId) {
      this.disableMany([modId])
    },
    disableMany(modIds) {
      const selected = new Set(modIds || [])
      const next = this.activeIds.filter(id => !selected.has(id))
      if (next.length !== this.activeIds.length) {
        this.activeIds = next
        this.dirty = true
        this.recordCurrentPlaysetChange()
      }
    },
    reorder(sourceId, targetId) {
      if (sourceId === targetId) return
      const sourceIndex = this.activeIds.indexOf(sourceId)
      const targetIndex = this.activeIds.indexOf(targetId)
      if (sourceIndex < 0 || targetIndex < 0) return
      const next = [...this.activeIds]
      next.splice(sourceIndex, 1)
      next.splice(targetIndex, 0, sourceId)
      this.activeIds = next
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    move(modId, direction) {
      const index = this.activeIds.indexOf(modId)
      const target = index + direction
      if (index < 0 || target < 0 || target >= this.activeIds.length) return
      const next = [...this.activeIds]
      ;[next[index], next[target]] = [next[target], next[index]]
      this.activeIds = next
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
      this.activeIds = next
      this.dirty = true
      this.recordCurrentPlaysetChange()
    },
    async toggleHiddenVisibility() {
      this.showHidden = !this.showHidden
      if (!this.showHidden && this.selectedMod?.hidden) {
        const next = [...this.activeMods, ...this.inactiveMods][0]
        this.selectedId = next?.id || ''
        this.selectedIds = this.selectedId ? [this.selectedId] : []
        this.selectionAnchorId = this.selectedId
        await this.loadPreview(this.selectedId)
      }
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
      return this.withBusy('启动游戏', async () => {
        const data = await invoke('launch_game', this.activeIds, this.orderToken)
        this.applyLaunchResult(data)
        this.notify(`Warhammer III 已启动（PID ${data.process.pid}）`)
        return data
      })
    },
    async continueGame() {
      await this.flushPlaysetUpdates()
      return this.withBusy('继续游戏', async () => {
        const data = await invoke('continue_game', this.activeIds, this.orderToken)
        this.applyLaunchResult(data)
        this.notify(`正在载入 ${data.save.name}`)
        return data
      })
    },
    async loadSaveGames() {
      return this.withBusy('读取存档列表', async () => {
        const data = await invoke('list_save_games')
        this.saveGames = data.items || []
        this.saveGamesDirectory = data.directory || ''
        return data
      })
    },
    async launchSave(saveName) {
      await this.flushPlaysetUpdates()
      return this.withBusy('载入指定存档', async () => {
        const data = await invoke('launch_game', this.activeIds, this.orderToken, saveName)
        this.applyLaunchResult(data)
        this.notify(`正在载入 ${data.save.name}`)
        return data
      })
    },
    async saveSettings(changes) {
      await this.flushPlaysetUpdates()
      return this.withBusy('保存设置', async () => {
        const data = await invoke('save_settings', changes)
        this.settings = data.settings
        applyInterfaceLanguage(this.settings.language)
        this.paths = data.paths
        this.pathHealth = data.path_health
        this.mods = []
        this.thumbnails = {}
        this.activeIds = []
        this.selectedId = ''
        this.selectedIds = []
        this.selectionAnchorId = ''
        this.dirty = false
        this.notify('设置已保存')
        return data
      })
    },
    async checkForUpdates(manual = true, manifestUrl = null) {
      if (this.updateChecking) return this.updateInfo
      this.updateChecking = true
      const execute = async () => {
        try {
          const data = manifestUrl === null
            ? await invoke('check_for_updates', manual)
            : await invoke('check_for_updates', manual, manifestUrl)
          this.updateInfo = data
          if (data.checked_at) this.settings.last_update_check_at = data.checked_at
          if (manifestUrl !== null && data.configured) this.settings.update_manifest_url = manifestUrl.trim()
          this.autoUpdateDue = false
          if (manual && !data.has_update) this.notify(`当前已是最新版本 v${this.appVersion}`)
          return data
        } catch (error) {
          if (!manual) {
            console.warn('自动检查更新失败', error)
            return null
          }
          throw error
        } finally {
          this.updateChecking = false
        }
      }
      if (manual) return this.withBusy('检查软件更新', execute)
      return execute()
    },
    async downloadUpdate() {
      const version = this.updateInfo?.version || ''
      return this.withBusy('下载并校验更新', async () => {
        const data = await invoke('download_update', version)
        this.updateInfo = data
        this.notify(`v${data.version} 已下载并通过校验`)
        return data
      })
    },
    async installUpdate() {
      const version = this.updateInfo?.version || ''
      return this.withBusy('准备安装更新', async () => {
        const data = await invoke('install_update', version)
        this.notify('正在退出并安装新版本')
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
      this.notify(`已忽略 v${version}；仍可手动检查并安装`)
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
    async detectPaths() {
      return this.withBusy('检测 Steam 路径', async () => {
        const data = await invoke('detect_paths')
        this.settings = data.settings
        applyInterfaceLanguage(this.settings.language)
        this.paths = data.paths
        const bootstrap = await invoke('get_bootstrap')
        this.pathHealth = bootstrap.path_health
        this.notify('已定位 Warhammer III')
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
      this.notify('MOD 信息已保存')
    },
    async generateModUserData(modId) {
      return this.withBusy('AI 生成标题和摘要备注', async () => {
        const updated = await invoke('generate_mod_user_data', modId)
        const index = this.mods.findIndex(mod => mod.id === updated.id)
        if (index >= 0) this.mods[index] = updated
        this.notify('AI 已生成并保存当前语言标题和摘要备注')
        return updated
      })
    },
    setSearchTokens(tokens) {
      this.searchTokens = Array.isArray(tokens) ? tokens : []
    },
    setSearchLogic(logic) {
      this.searchLogic = logic === 'OR' ? 'OR' : 'AND'
    },
    setSortMode(mode) {
      if (!SORT_OPTIONS.some(option => option.id === mode)) return
      this.sortMode = mode
      this.sortDescending = mode === 'updated' || mode === 'created'
    },
    setSortDescending(descending) {
      this.sortDescending = Boolean(descending)
    },
    async setModType(modId, typeId) {
      return this.withBusy('修改 MOD 类型', async () => {
        const updated = await invoke('set_mod_types', modId, [typeId])
        const index = this.mods.findIndex(mod => mod.id === updated.id)
        if (index >= 0) this.mods[index] = updated
        this.notify(`已修改类型为“${this.modTypeMap[typeId] || '未知'}”`)
        return updated
      })
    },
    async toggleModType(modId, typeId) {
      const mod = this.modMap.get(modId)
      if (!mod) throw new Error('MOD 不存在或尚未扫描')
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
      return this.withBusy('修改 MOD 类型', async () => {
        const updated = await invoke('set_mod_types', modId, next)
        const index = this.mods.findIndex(item => item.id === updated.id)
        if (index >= 0) this.mods[index] = updated
        const names = updated.mod_types.map(item => this.modTypeMap[item] || item).join('、')
        this.notify(`已设置类型：${names}`)
        return updated
      })
    },
    async setModHidden(modId, hidden) {
      return this.withBusy(hidden ? '隐藏 MOD' : '取消隐藏 MOD', async () => {
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
        this.notify(hidden ? '已从列表中隐藏 MOD' : '已取消隐藏 MOD')
        return updated
      })
    },
    async createModType(name) {
      return this.withBusy('新增 MOD 类型', async () => {
        const data = await invoke('create_mod_type', name)
        this.modTypes = data.items
        this.notify(`已新增类型“${data.item.name}”`)
        return data.item
      })
    },
    async updateModType(typeId, name) {
      return this.withBusy('修改 MOD 类型', async () => {
        const data = await invoke('update_mod_type', typeId, name)
        this.modTypes = data.items
        this.notify(`已修改类型为“${data.item.name}”`)
        return data.item
      })
    },
    async deleteModType(typeId) {
      return this.withBusy('删除 MOD 类型', async () => {
        const data = await invoke('delete_mod_type', typeId)
        this.modTypes = data.items
        this.mods = this.mods.map(mod => {
          const selected = (mod.mod_types?.length ? mod.mod_types : [mod.mod_type || 'unknown'])
            .filter(item => item !== typeId)
          const modTypes = selected.length ? selected : ['unknown']
          return { ...mod, mod_type: modTypes[0], mod_types: modTypes }
        })
        this.notify('自定义类型已删除，相关 MOD 的类型已同步更新')
      })
    },
    async exportShare() {
      return invoke('export_share', this.activeIds)
    },
    async importShare(value) {
      await this.flushPlaysetUpdates()
      return this.withBusy('导入到当前播放集', async () => {
        const data = await invoke('import_share', value)
        this.applyPlaysetPayload(data)
        this.dirty = true
        this.recordCurrentPlaysetChange()
        if (data.missing.length) {
          this.notify(`有 ${data.missing.length} 个项目未安装`, 'warning')
        } else {
          this.notify(`已更新当前播放集“${data.current_playset.name}”`)
        }
        return data
      })
    },
    async openModFolder(modId) {
      await invoke('open_mod_folder', modId)
    },
    async openWorkshopFolder(modId) {
      await invoke('open_workshop_folder', modId)
    },
    async openWorkshop(modId) {
      await invoke('open_workshop_page', modId)
    },
    async unsubscribeWorkshop(modId) {
      return this.withBusy('取消 Steam Workshop 订阅', async () => {
        const data = await invoke('unsubscribe_workshop_mod', modId)
        this.notify('Steam 已接受取消订阅请求')
        return data
      })
    },
    async forceUpdateWorkshop(modId) {
      return this.withBusy('请求 Steam 强制更新', async () => {
        const data = await invoke('force_update_workshop_mod', modId)
        this.notify('Steam 已接受高优先级更新请求')
        return data
      })
    },
    async publishWorkshopItem(modId, publishData) {
      const mode = publishData?.mode === 'update' ? 'update' : 'upload'
      return this.withBusy(mode === 'upload' ? '上传到 Steam Workshop' : '更新 Steam Workshop', async () => {
        const data = await invoke('publish_workshop_item', modId, publishData)
        const index = this.mods.findIndex(mod => mod.id === data.mod.id)
        if (index >= 0) this.mods[index] = data.mod
        const agreementNote = data.result.needs_to_accept_agreement
          ? '；还需在 Steam Workshop 接受创作者协议'
          : ''
        this.notify(`${mode === 'upload' ? '工坊项目已创建并上传' : '工坊项目已更新'}（ID ${data.result.workshop_id}）${agreementNote}`)
        return data
      })
    },
    async openModInRpfm(modId) {
      return this.withBusy('启动 RPFM', async () => {
        const data = await invoke('open_mod_in_rpfm', modId)
        this.notify('已在 RPFM 中打开 Pack')
        return data
      })
    },
    async copyModToData(modId) {
      const source = this.modMap.get(modId)
      const packName = source?.pack_name || ''
      const activeIndex = this.activeIds.indexOf(modId)
      const wasDirty = this.dirty
      const data = await this.withBusy('复制 MOD 到 Data', () => invoke('copy_mod_to_data', modId))
      if (!data.copied) {
        this.notify('该 MOD 已位于 Data 目录', 'warning')
        return data
      }
      await this.scan(false)
      const replacement = this.mods.find(mod => mod.pack_name.toLocaleLowerCase() === packName.toLocaleLowerCase())
      if (activeIndex >= 0 && replacement && !this.activeIds.includes(replacement.id)) {
        const next = [...this.activeIds]
        next.splice(Math.min(activeIndex, next.length), 0, replacement.id)
        this.activeIds = next
        this.dirty = wasDirty
        this.recordCurrentPlaysetChange()
      }
      if (replacement) await this.selectMod(replacement.id)
      this.notify(`已复制 ${packName} 到 Data 目录`)
      return data
    },
    async syncWorkshopToData() {
      const activePackNames = this.activeIds
        .map(id => this.modMap.get(id)?.pack_name)
        .filter(Boolean)
      const selectedPackName = this.selectedMod?.pack_name || ''
      const wasDirty = this.dirty
      const data = await this.withBusy(
        '同步工坊 MOD 到 Data',
        () => invoke('sync_workshop_to_data'),
      )
      if (data.copied || data.updated) {
        await this.scan(false)
        const byPackName = new Map(this.mods.map(mod => [mod.pack_name.toLocaleLowerCase(), mod.id]))
        this.activeIds = [...new Set(
          activePackNames
            .map(name => byPackName.get(name.toLocaleLowerCase()))
            .filter(Boolean),
        )]
        this.dirty = wasDirty
        this.recordCurrentPlaysetChange()
        if (selectedPackName) {
          const replacement = byPackName.get(selectedPackName.toLocaleLowerCase())
          if (replacement) await this.selectMod(replacement)
        }
      }
      const skipped = Number(data.skipped || 0)
      this.notify(
        `同步完成：新增 ${data.copied}，更新 ${data.updated}，未变化 ${data.unchanged}`
          + (skipped ? `，跳过 ${skipped}` : ''),
        skipped && !data.copied && !data.updated ? 'warning' : 'success',
      )
      return data
    },
    async openGameFolder() {
      await invoke('open_game_folder')
    },
    async refreshRuntime() {
      try {
        this.runtime = await invoke('get_runtime_status')
      } catch {
        // Runtime polling must never interrupt the main workflow.
      }
    },
  },
})
