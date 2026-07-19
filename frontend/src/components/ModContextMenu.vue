<script setup>
import { computed } from 'vue'
import { localizedModTypeName, t } from '../languages'
import { shortcutForAction } from '../keyboardShortcuts'

const props = defineProps({
  open: { type: Boolean, default: false },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  mod: { type: Object, default: null },
  active: { type: Boolean, default: false },
  types: { type: Array, default: () => [] },
  selectionCount: { type: Number, default: 1 },
  selectedModIds: { type: Array, default: () => [] },
  eligibleUpdateIds: { type: Array, default: () => [] },
  aiEnabled: { type: Boolean, default: false },
  gameRunning: { type: Boolean, default: false },
  keyboardShortcuts: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'action'])

const menuStyle = computed(() => {
  const width = 246
  const height = (props.mod?.workshop_id ? 540 : 500) + (showAiGenerate.value ? 44 : 0)
  const viewportWidth = typeof window === 'undefined' ? 1440 : window.innerWidth
  const viewportHeight = typeof window === 'undefined' ? 900 : window.innerHeight
  return {
    left: `${Math.max(8, Math.min(props.x, viewportWidth - width - 8))}px`,
    top: `${Math.max(8, Math.min(props.y, viewportHeight - height - 8))}px`,
  }
})

const submenuToLeft = computed(() => {
  const viewportWidth = typeof window === 'undefined' ? 1440 : window.innerWidth
  return props.x > viewportWidth - 510
})

const hasWorkshop = computed(() => !!props.mod?.workshop_id)
const sources = computed(() => new Set(props.mod?.sources?.length ? props.mod.sources : [props.mod?.source]))
const canCopyToData = computed(() => !!props.mod?.path && !sources.value.has('data'))
const selectedModIds = computed(() => [...new Set(
  (Array.isArray(props.selectedModIds) ? props.selectedModIds : [])
    .map(id => String(id || '').trim())
    .filter(Boolean),
)])
const eligibleUpdateIds = computed(() => new Set(
  (Array.isArray(props.eligibleUpdateIds) ? props.eligibleUpdateIds : [])
    .map(id => String(id || '').trim())
    .filter(Boolean),
))
const canUploadWorkshop = computed(() => sources.value.has('data') && !hasWorkshop.value)
const canUpdateWorkshop = computed(() => (
  hasWorkshop.value
  && selectedModIds.value.length > 0
  && selectedModIds.value.every(id => eligibleUpdateIds.value.has(id))
))
const deleteLabel = computed(() => (
  sources.value.has('data') && sources.value.has('workshop')
    ? t('context.deleteFromData')
    : t('context.deleteModFile')
))
const hasSteamActions = computed(() => (
  hasWorkshop.value || canUploadWorkshop.value || canUpdateWorkshop.value
))
const isBatchSelection = computed(() => Number(props.selectionCount) > 1)
const showAiGenerate = computed(() => props.aiEnabled && isBatchSelection.value)
const batchLabel = label => (
  isBatchSelection.value
    ? t('context.batchLabel', { label, count: Number(props.selectionCount) })
    : label
)
const selectedTypes = computed(() => new Set(
  props.mod?.mod_types?.length ? props.mod.mod_types : [props.mod?.mod_type || 'unknown'],
))
const ignoredWarningCodes = computed(() => new Set(props.mod?.ignored_warning_codes || []))
const shortcutLabel = action => shortcutForAction(action, props.keyboardShortcuts)

const run = (action, value = null, close = true) => {
  if (close) emit('close')
  emit('action', { action, value, mod: props.mod })
}
</script>

<template>
  <div
    v-if="open && mod"
    class="context-menu-layer"
    data-testid="mod-context-menu"
    @mousedown.self="emit('close')"
    @contextmenu.prevent
  >
    <nav class="context-menu" :class="{ 'submenus-left': submenuToLeft }" :style="menuStyle" role="menu" :aria-label="t('context.aria')">
      <button type="button" class="context-menu-item" role="menuitem" data-testid="context-toggle-active" @click="run('toggle-active')">
        <span class="context-menu-icon">{{ active ? '⊘' : '✓' }}</span>
        <span>{{ batchLabel(active ? t('list.disable') : t('list.enable')) }}</span>
        <kbd class="context-menu-shortcut">{{ shortcutLabel('toggle-active') }}</kbd>
      </button>

      <div class="context-menu-parent" data-testid="context-type-menu">
        <span class="context-menu-icon">◆</span>
        <span>{{ batchLabel(t('context.editType')) }}</span>
        <span class="context-menu-arrow">›</span>
        <div class="context-submenu type-submenu" role="menu">
          <button
            v-for="type in types"
            :key="type.id"
            type="button"
            class="context-menu-item"
            role="menuitemcheckbox"
            :aria-checked="selectedTypes.has(type.id)"
            :class="{ checked: selectedTypes.has(type.id) }"
            @click.stop="run('toggle-type', type.id, false)"
          >
            <span class="context-menu-check">{{ selectedTypes.has(type.id) ? '✓' : '' }}</span>
            <span>{{ batchLabel(localizedModTypeName(type)) }}</span>
          </button>
          <div class="context-menu-divider"></div>
          <button type="button" class="context-menu-item" role="menuitem" @click.stop="run('manage-types')">
            <span class="context-menu-icon">⚙</span>
            <span>{{ t('context.manageTypes') }}</span>
          </button>
        </div>
      </div>

      <div
        class="context-menu-parent"
        :class="{ disabled: !active }"
        :aria-disabled="!active"
        data-testid="context-move-menu"
      >
        <span class="context-menu-icon">↕</span>
        <span>{{ batchLabel(t('context.moveTo')) }}</span>
        <span v-if="active" class="context-menu-arrow">›</span>
        <span v-else class="context-menu-unavailable">{{ t('common.unavailable') }}</span>
        <div v-if="active" class="context-submenu" role="menu">
          <button type="button" class="context-menu-item" @click.stop="run('move-specific')">
            <span class="context-menu-icon">#</span><span>{{ batchLabel(t('context.specificOrder')) }}</span>
          </button>
          <button type="button" class="context-menu-item" @click.stop="run('move-top')">
            <span class="context-menu-icon">⇈</span><span>{{ batchLabel(t('context.listTop')) }}</span>
          </button>
          <button type="button" class="context-menu-item" @click.stop="run('move-bottom')">
            <span class="context-menu-icon">⇊</span><span>{{ batchLabel(t('context.listBottom')) }}</span>
          </button>
        </div>
      </div>

      <button
        v-if="hasWorkshop"
        type="button"
        class="context-menu-item"
        role="menuitem"
        data-testid="context-open-workshop-browser"
        @click="run('open-workshop-browser')"
      >
        <span class="context-menu-icon">↗</span>
        <span>{{ batchLabel(t('context.openWorkshopBrowser')) }}</span>
        <kbd class="context-menu-shortcut">{{ shortcutLabel('open-workshop') }}</kbd>
      </button>
      <button
        v-if="hasWorkshop"
        type="button"
        class="context-menu-item"
        role="menuitem"
        data-testid="context-open-workshop-client"
        @click="run('open-workshop-client')"
      >
        <span class="context-menu-icon steam-icon">S</span>
        <span>{{ batchLabel(t('context.openWorkshopClient')) }}</span>
      </button>

      <div
        class="context-menu-parent"
        :class="{ disabled: !hasSteamActions }"
        :aria-disabled="!hasSteamActions"
        data-testid="context-steam-menu"
      >
        <span class="context-menu-icon steam-icon">S</span>
        <span>{{ batchLabel(t('context.steamActions')) }}</span>
        <span v-if="hasSteamActions" class="context-menu-arrow">›</span>
        <span v-else class="context-menu-unavailable">{{ t('common.unavailable') }}</span>
        <div v-if="hasSteamActions" class="context-submenu" role="menu">
          <button
            v-if="hasWorkshop"
            type="button"
            class="context-menu-item danger-item"
            :disabled="gameRunning"
            :title="gameRunning ? t('context.gameRunningBlocked') : ''"
            @click.stop="run('unsubscribe')"
          >
            <span class="context-menu-icon">⊘</span><span>{{ batchLabel(t('context.unsubscribe')) }}</span>
          </button>
          <button v-if="hasWorkshop" type="button" class="context-menu-item" @click.stop="run('force-update')">
            <span class="context-menu-icon">↻</span><span>{{ batchLabel(t('context.forceUpdate')) }}</span>
          </button>
          <div v-if="hasWorkshop && (canUploadWorkshop || canUpdateWorkshop)" class="context-menu-divider"></div>
          <button
            v-if="canUploadWorkshop"
            type="button"
            class="context-menu-item"
            data-testid="context-publish-upload"
            @click.stop="run('publish-upload')"
          >
            <span class="context-menu-icon">↑</span><span>{{ batchLabel(t('context.uploadWorkshop')) }}</span>
          </button>
          <button
            v-if="canUpdateWorkshop"
            type="button"
            class="context-menu-item"
            data-testid="context-publish-update"
            @click.stop="run('publish-update')"
          >
            <span class="context-menu-icon">⇧</span><span>{{ batchLabel(t('context.updateWorkshop')) }}</span>
          </button>
        </div>
      </div>

      <div class="context-menu-parent" data-testid="context-ignore-warning-menu">
        <span class="context-menu-icon">!</span>
        <span>{{ batchLabel(t('context.ignoreIssue')) }}</span>
        <span class="context-menu-arrow">›</span>
        <div class="context-submenu" role="menu">
          <button
            type="button"
            class="context-menu-item"
            role="menuitemcheckbox"
            :aria-checked="ignoredWarningCodes.has('outdated_mod')"
            :class="{ checked: ignoredWarningCodes.has('outdated_mod') }"
            @click.stop="run('toggle-warning-ignore', 'outdated_mod', false)"
          >
            <span class="context-menu-check">{{ ignoredWarningCodes.has('outdated_mod') ? '✓' : '' }}</span>
            <span>{{ batchLabel(t('context.ignoreOutdated')) }}</span>
          </button>
          <button
            type="button"
            class="context-menu-item"
            role="menuitemcheckbox"
            :aria-checked="ignoredWarningCodes.has('missing_dependency')"
            :class="{ checked: ignoredWarningCodes.has('missing_dependency') }"
            @click.stop="run('toggle-warning-ignore', 'missing_dependency', false)"
          >
            <span class="context-menu-check">{{ ignoredWarningCodes.has('missing_dependency') ? '✓' : '' }}</span>
            <span>{{ batchLabel(t('context.ignoreDependency')) }}</span>
          </button>
        </div>
      </div>

      <div class="context-menu-divider"></div>

      <button type="button" class="context-menu-item" @click="run('copy-path')">
        <span class="context-menu-icon">⧉</span>
        <span>{{ batchLabel(t('context.copyModPath')) }}</span>
      </button>
      <button
        type="button"
        class="context-menu-item danger-item"
        :disabled="gameRunning"
        :title="gameRunning ? t('context.gameRunningBlocked') : ''"
        @click="run('delete-file')"
      >
        <span class="context-menu-icon">×</span>
        <span>{{ batchLabel(deleteLabel) }}</span>
      </button>

      <button type="button" class="context-menu-item" @click="run('open-folder')">
        <span class="context-menu-icon">▣</span>
        <span>{{ batchLabel(t('context.openFileFolder')) }}</span>
      </button>
      <button
        type="button"
        class="context-menu-item"
        :disabled="isBatchSelection"
        :title="isBatchSelection ? t('context.rpfmBatchTitle') : ''"
        data-testid="context-open-rpfm"
        @click="run('open-rpfm')"
      >
        <span class="context-menu-icon">R</span>
        <span>{{ t('context.openRpfm') }}</span>
        <span class="context-menu-trailing">
          <kbd class="context-menu-shortcut">{{ shortcutLabel('open-rpfm') }}</kbd>
          <span v-if="isBatchSelection" class="context-menu-unavailable">{{ t('common.singleOnly') }}</span>
        </span>
      </button>
      <button type="button" class="context-menu-item" @click="run('toggle-hidden')">
        <span class="context-menu-icon">{{ mod.hidden ? '◉' : '◌' }}</span>
        <span>{{ batchLabel(mod.hidden ? t('context.unhide') : t('context.hide')) }}</span>
      </button>
      <button
        type="button"
        class="context-menu-item"
        :disabled="!canCopyToData"
        :title="canCopyToData ? '' : t('context.existsData')"
        @click="run('copy-to-data')"
      >
        <span class="context-menu-icon">⇩</span>
        <span>{{ batchLabel(t('context.copyToData')) }}</span>
        <span v-if="!canCopyToData" class="context-menu-unavailable">{{ t('context.inData') }}</span>
      </button>
      <button
        v-if="showAiGenerate"
        type="button"
        class="context-menu-item"
        data-testid="context-generate-user-data"
        @click="run('generate-user-data')"
      >
        <span class="context-menu-icon">AI</span>
        <span>{{ batchLabel(t('context.aiGenerate')) }}</span>
      </button>
    </nav>
  </div>
</template>
