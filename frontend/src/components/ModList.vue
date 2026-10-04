<script setup>
import { computed, nextTick, onBeforeUnmount, onUpdated, ref, watch } from 'vue'
import { localizeBackendMessage, t } from '../languages'
import SortMenu from './SortMenu.vue'
import TagSearchBox from './TagSearchBox.vue'
import { buildFolderGroups } from '../modFolderLayout'
import { createDragFeedback } from '../dragFeedback'

const props = defineProps({
  title: { type: String, required: true },
  mods: { type: Array, default: () => [] },
  active: { type: Boolean, default: false },
  selectedId: { type: String, default: '' },
  selectedIds: { type: Array, default: () => [] },
  orderIds: { type: Array, default: () => [] },
  thumbnails: { type: Object, default: () => ({}) },
  typeMap: { type: Object, default: () => ({}) },
  visualSorted: { type: Boolean, default: false },
  warningCount: { type: Number, default: 0 },
  warningsOnly: { type: Boolean, default: false },
  searchTokens: { type: Array, default: () => [] },
  searchLogic: { type: String, default: 'AND' },
  searchSuggestionMods: { type: Array, default: () => [] },
  searchTestId: { type: String, default: 'tag-search-box' },
  searchHighlightMode: { type: Boolean, default: false },
  searchHighlightTestId: { type: String, default: 'search-highlight-button' },
  sortMode: { type: String, default: 'priority' },
  sortDescending: { type: Boolean, default: false },
  sortTestId: { type: String, default: 'sort-button' },
  searchActive: { type: Boolean, default: false },
  searchMatchIds: { type: Array, default: () => [] },
  searchFocusId: { type: String, default: '' },
  dragSource: { type: Object, default: null },
  unitDataModIds: { type: Array, default: () => [] },
  folders: { type: Array, default: () => [] },
  folderLayout: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits([
  'select',
  'enable',
  'disable',
  'drop-mods',
  'drag-start',
  'drag-end',
  'move',
  'context-menu',
  'show-warnings',
  'toggle-warnings-only',
  'select-all',
  'toggle-active',
  'update:search-tokens',
  'update:search-logic',
  'toggle-search-highlight',
  'update:sort-mode',
  'update:sort-descending',
  'open-unit-data',
  'toggle-folder',
  'rename-folder',
  'delete-folder',
  'move-folder',
  'folder-drag-start',
])
const draggingIds = ref([])
const draggingOriginId = ref('')
let draggingFolderId = ''
let folderDropPreview = null
let dropPreview = null
const listElement = ref(null)
const insertionMarker = ref(null)
const dragFeedback = createDragFeedback(() => listElement.value, () => insertionMarker.value)
onUpdated(() => dragFeedback.restore())
onBeforeUnmount(() => dragFeedback.clear())
const rowElements = new Map()
const displayGroups = computed(() => {
  const searching = props.searchTokens.length > 0 || props.searchActive || props.warningsOnly
  const groups = buildFolderGroups(props.mods, props.folders, props.folderLayout, searching)
  return groups.map(group => {
    const collapsed = Boolean(group.folder?.[props.active ? 'collapsed_active' : 'collapsed_inactive'])
    const expanded = !collapsed || searching || group.mods.some(mod => mod.id === props.searchFocusId)
    return { ...group, expanded, visibleMods: expanded ? group.mods : [] }
  })
})
const visibleMods = computed(() => displayGroups.value.flatMap(group => group.visibleMods))

const orderPositions = computed(() => new Map(props.orderIds.map((id, index) => [id, index + 1])))
const positionOf = modId => orderPositions.value.get(modId) || 0
const sourcesOf = mod => [...new Set(mod.sources?.length ? mod.sources : [mod.source])]
const sourceLabel = source => ({
  workshop: t('list.workshopSource'),
  data: t('list.dataSource'),
  local: t('list.localSource'),
}[source] || String(source).toUpperCase())
const authorOf = mod => mod.author?.trim() || (mod.workshop_id ? t('list.authorUnavailable') : t('list.localFile'))
const typesOf = mod => [...new Set(mod.mod_types?.length ? mod.mod_types : [mod.mod_type || 'unknown'])]
const isSelected = modId => props.selectedIds.includes(modId) || props.selectedId === modId
const isSearchMatch = modId => props.searchActive && props.searchMatchIds.includes(modId)
const isSearchMuted = modId => props.searchActive && !isSearchMatch(modId)
const setRowElement = (modId, element) => {
  if (element) rowElements.set(modId, element)
  else rowElements.delete(modId)
}
const warningsOf = mod => (mod.warnings || []).filter(
  warning => props.active || warning?.code !== 'missing_dependency',
)
const canOpenUnitData = mod => props.unitDataModIds.includes(mod.id)
const targetList = () => (props.active ? 'active' : 'inactive')
const currentDragSource = () => (
  (props.dragSource?.kind === 'folder' ? null : props.dragSource) || (draggingIds.value.length
    ? {
        source: targetList(),
        ids: draggingIds.value,
        draggedId: draggingOriginId.value,
      }
    : null)
)
const canAcceptDrop = targetId => {
  const source = currentDragSource()
  if (!source) return true
  if (props.active && props.sortMode !== 'priority' && source.source === 'active') return false
  return !(source.source === targetList() && targetId && source.ids?.includes(targetId))
}
const clearDropPreview = () => {
  dropPreview = null
  folderDropPreview = null
  dragFeedback.clearPreview()
}

const currentFolderDrag = () => (
  props.dragSource?.kind === 'folder' ? props.dragSource.folderId : draggingFolderId
)
const dropPlacement = event => {
  const bounds = event.currentTarget?.getBoundingClientRect?.()
  return !bounds || event.clientY < bounds.top + bounds.height / 2 ? 'before' : 'after'
}
const onFolderDragStart = (event, folderId) => {
  if (props.busy || event.target?.closest?.('.icon-button')) {
    event.preventDefault()
    return
  }
  draggingFolderId = folderId
  dragFeedback.setSource(event.currentTarget)
  const payload = { kind: 'folder', folderId, source: targetList() }
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('application/x-wyccc-folder', JSON.stringify(payload))
  }
  emit('folder-drag-start', payload)
}
const onFolderDragOver = (event, targetFolderId) => {
  if (!currentFolderDrag() || props.busy || currentFolderDrag() === targetFolderId) {
    clearDropPreview()
    return
  }
  event.preventDefault()
  const placement = dropPlacement(event)
  folderDropPreview = { targetFolderId, targetModId: '', placement }
  dragFeedback.showTarget(event.currentTarget, placement)
}
const onFolderDrop = (event, targetFolderId = '', targetModId = '') => {
  let folderId = currentFolderDrag()
  if (!folderId) {
    try { folderId = JSON.parse(event.dataTransfer?.getData('application/x-wyccc-folder') || 'null')?.folderId } catch { /* Ignore unrelated drags. */ }
  }
  if (folderId && folderId !== targetFolderId && !props.busy) {
    const preview = folderDropPreview
    const placement = preview?.targetFolderId === targetFolderId && preview?.targetModId === targetModId
      ? preview.placement : dropPlacement(event)
    emit('move-folder', { folderId, targetFolderId, targetModId, placement, listName: targetList() })
  }
  clearDragging()
}

const selectMod = (event, mod) => {
  emit('select', {
    id: mod.id,
    ctrlKey: Boolean(event.ctrlKey),
    metaKey: Boolean(event.metaKey),
    shiftKey: Boolean(event.shiftKey),
    orderedIds: visibleMods.value.map(item => item.id),
  })
}

const onDoubleClick = (event, mod) => {
  const target = event.target instanceof Element ? event.target : null
  if (target?.closest('button, a, input, textarea, select, [contenteditable]')) return
  emit('toggle-active', mod.id)
}

const onContextMenu = (event, mod) => {
  emit('context-menu', { x: event.clientX, y: event.clientY, mod, active: props.active })
}

const isEditableTarget = target => {
  const element = target instanceof Element ? target : null
  if (!element) return false
  return Boolean(
    element.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]'),
  )
}

const onKeydown = event => {
  if (!event.ctrlKey || event.altKey || event.key.toLocaleLowerCase() !== 'a') return
  if (isEditableTarget(event.target) || !visibleMods.value.length) return
  event.preventDefault()
  emit('select-all', visibleMods.value.map(mod => mod.id))
}

const clearDragging = () => {
  draggingIds.value = []
  draggingOriginId.value = ''
  draggingFolderId = ''
  clearDropPreview()
  dragFeedback.clear()
  emit('drag-end')
}

const onDragStart = (event, sourceId) => {
  const visibleOrder = visibleMods.value.map(mod => mod.id)
  const visibleIds = new Set(visibleOrder)
  const selected = new Set([...props.selectedIds, props.selectedId].filter(Boolean))
  draggingIds.value = selected.has(sourceId)
    ? visibleOrder.filter(id => selected.has(id) && visibleIds.has(id))
    : [sourceId]
  if (!draggingIds.value.length) draggingIds.value = [sourceId]
  draggingOriginId.value = sourceId
  const payload = {
    source: targetList(),
    ids: draggingIds.value,
    draggedId: sourceId,
    sourceOrder: visibleOrder,
  }
  emit('drag-start', payload)
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('application/x-wyccc-mods', JSON.stringify(payload))
    event.dataTransfer.setData('text/plain', draggingIds.value.join('\n'))
  }
}

const onRowDragOver = (event, targetId) => {
  if (currentFolderDrag()) {
    if (!props.busy) {
      const placement = dropPlacement(event)
      folderDropPreview = { targetFolderId: '', targetModId: targetId, placement }
      dragFeedback.showTarget(event.currentTarget, placement)
    }
    return
  }
  if (!canAcceptDrop(targetId)) {
    clearDropPreview()
    return
  }
  const bounds = event.currentTarget?.getBoundingClientRect?.()
  const placement = !bounds || event.clientY < bounds.top + bounds.height / 2
    ? 'before'
    : 'after'
  dropPreview = { targetId, placement }
  dragFeedback.showTarget(event.currentTarget, placement)
}

const onListDragOver = event => {
  if (event.target instanceof Element && event.target.closest('.mod-row, .mod-folder-row')) return
  if (currentFolderDrag()) {
    folderDropPreview = { targetFolderId: '', targetModId: '', placement: 'after' }
    dragFeedback.showEnd()
    return
  }
  if (!canAcceptDrop()) return
  dropPreview = { targetId: '', placement: 'after' }
  dragFeedback.showEnd()
}

const onListDragLeave = event => {
  const nextTarget = event.relatedTarget
  if (nextTarget instanceof Node && event.currentTarget?.contains(nextTarget)) return
  clearDropPreview()
}

const onDrop = (event, targetId = '') => {
  if (currentFolderDrag() || event.dataTransfer?.getData('application/x-wyccc-folder')) {
    onFolderDrop(event, '', targetId)
    return
  }
  if (!canAcceptDrop(targetId)) {
    clearDragging()
    return
  }
  let payload = null
  try {
    const encoded = event.dataTransfer?.getData('application/x-wyccc-mods')
    if (encoded) payload = JSON.parse(encoded)
  } catch {
    payload = null
  }
  if (!payload && draggingIds.value.length) {
    payload = {
      source: props.active ? 'active' : 'inactive',
      ids: [...draggingIds.value],
      draggedId: draggingOriginId.value,
      sourceOrder: visibleMods.value.map(mod => mod.id),
    }
  }
  if (payload?.ids?.length) {
    const placement = dropPreview?.targetId === targetId
      ? dropPreview.placement
      : ''
    emit('drop-mods', {
      ...payload,
      target: props.active ? 'active' : 'inactive',
      targetId,
      targetOrder: visibleMods.value.map(mod => mod.id),
      ...(placement ? { placement } : {}),
    })
  }
  clearDragging()
}

watch(
  () => props.dragSource,
  source => { if (!source) clearDropPreview() },
)

watch(
  () => props.searchFocusId,
  modId => {
    if (!modId) return
    nextTick(() => rowElements.get(modId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  },
  { flush: 'post', immediate: true },
)
</script>

<template>
  <section class="list-panel" :class="{ 'active-panel': active }">
    <header class="panel-heading">
      <div class="panel-heading-row">
        <div>
          <span v-if="active" class="eyebrow">{{ t('list.loadOrder') }}</span>
          <h2>{{ title }}</h2>
        </div>
        <button
          v-if="active && (warningCount || warningsOnly)"
          type="button"
          class="panel-warning-button"
          :class="{ active: warningsOnly }"
          data-testid="panel-warning-button"
          :title="t(warningsOnly ? 'warnings.filterActiveHelp' : 'warnings.buttonHelp')"
          :aria-label="t(warningsOnly ? 'warnings.filterActiveHelp' : 'warnings.buttonHelp')"
          :aria-pressed="warningsOnly"
          @click="emit('show-warnings')"
          @contextmenu.prevent="emit('toggle-warnings-only')"
        >
          <span aria-hidden="true">!</span>
          {{ t('common.warningCount', { count: warningCount }) }}
        </button>
        <span class="count-badge">{{ mods.length }}</span>
      </div>
      <div class="panel-search-controls">
        <TagSearchBox
          :tokens="searchTokens"
          :logic="searchLogic"
          :mods="searchSuggestionMods"
          :type-map="typeMap"
          :test-id="searchTestId"
          @update:tokens="emit('update:search-tokens', $event)"
          @update:logic="emit('update:search-logic', $event)"
        />
        <button
          type="button"
          class="search-highlight-button"
          :class="{ active: searchHighlightMode }"
          :aria-pressed="searchHighlightMode"
          :title="t('search.highlightModeHelp')"
          :aria-label="t('search.highlightModeHelp')"
          :data-testid="searchHighlightTestId"
          @click="emit('toggle-search-highlight')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="5.5"></circle>
            <path d="m15.2 15.2 4.3 4.3M11 8.5v5M8.5 11h5"></path>
          </svg>
        </button>
        <SortMenu
          :mode="sortMode"
          :descending="sortDescending"
          :test-id="sortTestId"
          @update:mode="emit('update:sort-mode', $event)"
          @update:descending="emit('update:sort-descending', $event)"
        />
      </div>
    </header>

    <div
      ref="listElement"
      class="mod-list"
      data-testid="mod-list"
      tabindex="0"
      @keydown="onKeydown"
      @dragover.prevent="onListDragOver"
      @dragleave="onListDragLeave"
      @drop.prevent="onDrop($event)"
    >
      <template v-for="group in displayGroups" :key="group.key">
        <div v-if="group.folder" class="mod-folder-row" :data-testid="`mod-folder-${group.folder.id}`"
          :draggable="!busy"
          @dragstart.stop="onFolderDragStart($event, group.folder.id)"
          @dragend.stop="clearDragging"
          @dragover.stop="onFolderDragOver($event, group.folder.id)"
          @drop.prevent.stop="onFolderDrop($event, group.folder.id)">
          <button
            type="button"
            class="mod-folder-toggle"
            :aria-expanded="group.expanded"
            :disabled="busy"
            :title="t('folders.orderHelp')"
            @click="emit('toggle-folder', group.folder.id, active ? 'active' : 'inactive')"
          >
            <span class="mod-folder-chevron" aria-hidden="true">{{ group.expanded ? '▾' : '▸' }}</span>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h7l2 3h9v11H3z" /></svg>
            <span class="mod-folder-name" :title="group.folder.name">{{ group.folder.name }}</span>
            <span class="count-badge">{{ group.mods.length }}</span>
          </button>
          <button type="button" class="icon-button" :disabled="busy"
            :title="t('folders.rename')" :aria-label="t('folders.rename')"
            @click="emit('rename-folder', group.folder)">✎</button>
          <button type="button" class="icon-button danger" :disabled="busy"
            :title="t('folders.deleteHelp')" :aria-label="t('folders.delete')"
            @click="emit('delete-folder', group.folder)">×</button>
        </div>
        <div
          v-for="mod in group.visibleMods"
          :key="mod.id"
          :ref="element => setRowElement(mod.id, element)"
          class="mod-row"
          :class="{
            selected: isSelected(mod.id),
            dragging: draggingIds.includes(mod.id),
            'source-duplicate': mod.cross_source_duplicate,
            'hidden-mod': mod.hidden,
            'visual-sorted': visualSorted,
            'search-match': isSearchMatch(mod.id),
            'search-muted': isSearchMuted(mod.id),
            'in-folder': !!group.folder,
          }"
          role="button"
          tabindex="0"
          :aria-selected="isSelected(mod.id)"
          draggable="true"
          @click="selectMod($event, mod)"
          @dblclick="onDoubleClick($event, mod)"
          @keydown.enter="selectMod($event, mod)"
          @keydown.space.prevent="selectMod($event, mod)"
          @contextmenu.prevent.stop="onContextMenu($event, mod)"
          @dragstart="onDragStart($event, mod.id)"
          @dragend="clearDragging"
          @dragover.prevent.stop="onRowDragOver($event, mod.id)"
          @drop.prevent.stop="onDrop($event, mod.id)"
        >
          <span class="mod-thumbnail">
            <img
              v-if="thumbnails[mod.id]"
              :src="thumbnails[mod.id]"
              :alt="t('list.previewAlt', { name: mod.effective_name })"
              loading="lazy"
            />
            <span v-else class="mod-thumbnail-placeholder" aria-hidden="true">
              <svg viewBox="0 0 24 24" focusable="false">
                <path d="M4 5.5h16v13H4zM6.5 16l3.5-4 2.5 2.7 2.2-2.2 2.8 3.5M16.5 9a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z" />
              </svg>
            </span>
            <span v-if="active" class="thumbnail-order">{{ positionOf(mod.id) }}</span>
          </span>

          <span class="row-copy">
            <span class="row-title" :title="mod.effective_name">{{ mod.effective_name }}</span>
            <span class="row-subtitle" :title="mod.pack_name">{{ mod.pack_name }}</span>
            <span class="row-badges">
              <span
                v-for="source in sourcesOf(mod)"
                :key="source"
                class="source-badge"
                :class="`source-${source}`"
              >
                {{ sourceLabel(source) }}
              </span>
              <span v-if="mod.pack_type === 'movie'" class="movie-badge">{{ t('list.movie') }}</span>
              <span v-for="typeId in typesOf(mod)" :key="typeId" class="mod-type-badge">
                {{ typeMap[typeId] || typeId }}
              </span>
              <span
                v-if="warningsOf(mod).length"
                class="mod-warning-badge"
                :class="{ error: warningsOf(mod).some(item => item.code === 'missing_dependency' || item.severity === 'error') }"
                :title="warningsOf(mod).map(item => localizeBackendMessage(item.message || item, 'warnings.genericScan')).join('\n')"
                data-testid="mod-warning-badge"
              >
                {{ warningsOf(mod).some(item => item.code === 'missing_dependency') ? t('list.missingDependency') : t('list.warning') }}
              </span>
              <span v-if="mod.hidden" class="hidden-badge">{{ t('list.hidden') }}</span>
              <span class="mod-author" :class="{ muted: !mod.author }" :title="authorOf(mod)">
                {{ authorOf(mod) }}
              </span>
            </span>
          </span>

          <span v-if="active" class="row-actions">
            <button
              v-if="canOpenUnitData(mod)"
              type="button"
              class="icon-button unit-data-action"
              :title="t('list.openUnitData')"
              :aria-label="t('list.openUnitData')"
              :data-testid="`open-unit-data-${mod.id}`"
              @click.stop="emit('open-unit-data', mod)"
            >⚙</button>
            <button
              type="button"
              class="icon-button"
              :title="visualSorted ? t('list.prioritySortRequired') : t('list.moveUp')"
              :disabled="visualSorted || positionOf(mod.id) <= 1"
              @click.stop="emit('move', mod.id, -1)"
            >↑</button>
            <button
              type="button"
              class="icon-button"
              :title="visualSorted ? t('list.prioritySortRequired') : t('list.moveDown')"
              :disabled="visualSorted || positionOf(mod.id) >= orderIds.length"
              @click.stop="emit('move', mod.id, 1)"
            >↓</button>
            <button
              type="button"
              class="icon-button danger"
              :title="t('list.disable')"
              @click.stop="emit('disable', mod.id)"
            >−</button>
          </span>
          <span v-else class="row-actions">
            <button
              v-if="canOpenUnitData(mod)"
              type="button"
              class="icon-button unit-data-action"
              :title="t('list.openUnitData')"
              :aria-label="t('list.openUnitData')"
              :data-testid="`open-unit-data-${mod.id}`"
              @click.stop="emit('open-unit-data', mod)"
            >⚙</button>
            <button
              type="button"
              class="enable-button"
              :title="t('list.enable')"
              @click.stop="emit('enable', mod.id)"
            >＋</button>
          </span>
        </div>
      </template>

      <div
        ref="insertionMarker"
        class="drop-insertion-marker"
        hidden
        aria-hidden="true"
      ></div>

      <div v-if="displayGroups.length === 0" class="empty-state">
        <span class="empty-mark">W</span>
        <p>{{ warningsOnly ? t('warnings.noMatchingMods') : active ? t('list.emptyActive') : t('list.emptyFiltered') }}</p>
        <button
          v-if="warningsOnly"
          type="button"
          class="secondary-button"
          data-testid="clear-warning-filter"
          @click="emit('toggle-warnings-only')"
        >{{ t('warnings.showAllMods') }}</button>
      </div>
    </div>
  </section>
</template>
