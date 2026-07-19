<script setup>
import { nextTick, ref, watch } from 'vue'
import { localizeBackendMessage, t } from '../languages'

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
  searchActive: { type: Boolean, default: false },
  searchMatchIds: { type: Array, default: () => [] },
  searchFocusId: { type: String, default: '' },
})

const emit = defineEmits([
  'select',
  'enable',
  'disable',
  'drop-mods',
  'move',
  'context-menu',
  'show-warnings',
  'select-all',
  'toggle-active',
])
const draggingIds = ref([])
const draggingOriginId = ref('')
const rowElements = new Map()

const positionOf = modId => props.orderIds.indexOf(modId) + 1
const sourcesOf = mod => [...new Set(mod.sources?.length ? mod.sources : [mod.source])]
const sourceLabel = source => ({
  workshop: t('list.workshopSource'),
  data: t('list.dataSource'),
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

const selectMod = (event, mod) => {
  emit('select', {
    id: mod.id,
    ctrlKey: Boolean(event.ctrlKey),
    metaKey: Boolean(event.metaKey),
    shiftKey: Boolean(event.shiftKey),
    orderedIds: props.mods.map(item => item.id),
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
  if (isEditableTarget(event.target) || !props.mods.length) return
  event.preventDefault()
  emit('select-all', props.mods.map(mod => mod.id))
}

const clearDragging = () => {
  draggingIds.value = []
  draggingOriginId.value = ''
}

const onDragStart = (event, sourceId) => {
  const visibleOrder = props.mods.map(mod => mod.id)
  const visibleIds = new Set(visibleOrder)
  const selected = new Set([...props.selectedIds, props.selectedId].filter(Boolean))
  draggingIds.value = selected.has(sourceId)
    ? visibleOrder.filter(id => selected.has(id) && visibleIds.has(id))
    : [sourceId]
  if (!draggingIds.value.length) draggingIds.value = [sourceId]
  draggingOriginId.value = sourceId
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('application/x-wyccc-mods', JSON.stringify({
      source: props.active ? 'active' : 'inactive',
      ids: draggingIds.value,
      draggedId: sourceId,
      sourceOrder: visibleOrder,
    }))
    event.dataTransfer.setData('text/plain', draggingIds.value.join('\n'))
  }
}

const onDrop = (event, targetId = '') => {
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
      sourceOrder: props.mods.map(mod => mod.id),
    }
  }
  if (payload?.ids?.length) {
    emit('drop-mods', {
      ...payload,
      target: props.active ? 'active' : 'inactive',
      targetId,
      targetOrder: props.mods.map(mod => mod.id),
    })
  }
  clearDragging()
}

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
      <div>
        <span v-if="active" class="eyebrow">{{ t('list.loadOrder') }}</span>
        <h2>{{ title }}</h2>
      </div>
      <button
        v-if="active && warningCount"
        type="button"
        class="panel-warning-button"
        data-testid="panel-warning-button"
        @click="emit('show-warnings')"
      >
        <span aria-hidden="true">!</span>
        {{ t('common.warningCount', { count: warningCount }) }}
      </button>
      <span class="count-badge">{{ mods.length }}</span>
    </header>

    <div
      class="mod-list"
      data-testid="mod-list"
      tabindex="0"
      @keydown="onKeydown"
      @dragover.prevent
      @drop.prevent="onDrop($event)"
    >
      <div
        v-for="mod in mods"
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
        @dragover.prevent
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
        <button
          v-else
          type="button"
          class="enable-button"
          :title="t('list.enable')"
          @click.stop="emit('enable', mod.id)"
        >＋</button>
      </div>

      <div v-if="mods.length === 0" class="empty-state">
        <span class="empty-mark">W</span>
        <p>{{ active ? t('list.emptyActive') : t('list.emptyFiltered') }}</p>
      </div>
    </div>
  </section>
</template>
