<script setup>
import { ref } from 'vue'

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
})

const emit = defineEmits(['select', 'enable', 'disable', 'reorder', 'move', 'context-menu'])
const draggingId = ref('')

const sourceLabel = {
  workshop: 'WORKSHOP',
  data: 'DATA',
}

const positionOf = modId => props.orderIds.indexOf(modId) + 1
const sourcesOf = mod => [...new Set(mod.sources?.length ? mod.sources : [mod.source])]
const authorOf = mod => mod.author?.trim() || (mod.workshop_id ? '作者昵称暂不可用' : '本地文件')
const typesOf = mod => [...new Set(mod.mod_types?.length ? mod.mod_types : [mod.mod_type || 'unknown'])]
const isSelected = modId => props.selectedIds.includes(modId) || props.selectedId === modId

const selectMod = (event, mod) => {
  emit('select', {
    id: mod.id,
    ctrlKey: Boolean(event.ctrlKey),
    metaKey: Boolean(event.metaKey),
    shiftKey: Boolean(event.shiftKey),
    orderedIds: props.mods.map(item => item.id),
  })
}

const onContextMenu = (event, mod) => {
  emit('context-menu', { x: event.clientX, y: event.clientY, mod, active: props.active })
}

const onDrop = (targetId) => {
  if (props.active && !props.visualSorted && draggingId.value) emit('reorder', draggingId.value, targetId)
  draggingId.value = ''
}
</script>

<template>
  <section class="list-panel" :class="{ 'active-panel': active }">
    <header class="panel-heading">
      <div>
        <span class="eyebrow">{{ active ? 'LOAD ORDER' : 'LIBRARY' }}</span>
        <h2>{{ title }}</h2>
      </div>
      <span class="count-badge">{{ mods.length }}</span>
    </header>

    <div class="mod-list" data-testid="mod-list">
      <div
        v-for="mod in mods"
        :key="mod.id"
        class="mod-row"
        :class="{
          selected: isSelected(mod.id),
          dragging: draggingId === mod.id,
          'source-duplicate': mod.cross_source_duplicate,
          'hidden-mod': mod.hidden,
          'visual-sorted': visualSorted,
        }"
        role="button"
        tabindex="0"
        :aria-selected="isSelected(mod.id)"
        :draggable="active && !visualSorted"
        @click="selectMod($event, mod)"
        @keydown.enter="selectMod($event, mod)"
        @keydown.space.prevent="selectMod($event, mod)"
        @contextmenu.prevent.stop="onContextMenu($event, mod)"
        @dragstart="draggingId = mod.id"
        @dragend="draggingId = ''"
        @dragover.prevent
        @drop.prevent="onDrop(mod.id)"
      >
        <span class="mod-thumbnail">
          <img
            v-if="thumbnails[mod.id]"
            :src="thumbnails[mod.id]"
            :alt="`${mod.effective_name} 预览图`"
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
              {{ sourceLabel[source] || source.toUpperCase() }}
            </span>
            <span v-if="mod.pack_type === 'movie'" class="movie-badge">MOVIE</span>
            <span v-for="typeId in typesOf(mod)" :key="typeId" class="mod-type-badge">
              {{ typeMap[typeId] || typeId }}
            </span>
            <span
              v-if="mod.warnings?.length"
              class="mod-warning-badge"
              :class="{ error: mod.warnings.some(item => item.code === 'missing_dependency' || item.severity === 'error') }"
              :title="mod.warnings.map(item => item.message || item).join('\n')"
              data-testid="mod-warning-badge"
            >
              {{ mod.warnings.some(item => item.code === 'missing_dependency') ? '! 缺少依赖' : '! 警告' }}
            </span>
            <span v-if="mod.hidden" class="hidden-badge">已隐藏</span>
            <span class="mod-author" :class="{ muted: !mod.author }" :title="authorOf(mod)">
              {{ authorOf(mod) }}
            </span>
          </span>
        </span>

        <span v-if="active" class="row-actions">
          <button
            type="button"
            class="icon-button"
            :title="visualSorted ? '切换回“优先级”排序后可调整实际加载顺序' : '上移'"
            :disabled="visualSorted || positionOf(mod.id) <= 1"
            @click.stop="emit('move', mod.id, -1)"
          >↑</button>
          <button
            type="button"
            class="icon-button"
            :title="visualSorted ? '切换回“优先级”排序后可调整实际加载顺序' : '下移'"
            :disabled="visualSorted || positionOf(mod.id) >= orderIds.length"
            @click.stop="emit('move', mod.id, 1)"
          >↓</button>
          <button
            type="button"
            class="icon-button danger"
            title="停用"
            @click.stop="emit('disable', mod.id)"
          >−</button>
        </span>
        <button
          v-else
          type="button"
          class="enable-button"
          title="启用"
          @click.stop="emit('enable', mod.id)"
        >＋</button>
      </div>

      <div v-if="mods.length === 0" class="empty-state">
        <span class="empty-mark">W</span>
        <p>{{ active ? '尚未启用任何 Pack' : '没有符合筛选条件的 Pack' }}</p>
      </div>
    </div>
  </section>
</template>
