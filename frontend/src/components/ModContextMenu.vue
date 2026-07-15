<script setup>
import { computed } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  mod: { type: Object, default: null },
  active: { type: Boolean, default: false },
  types: { type: Array, default: () => [] },
  selectionCount: { type: Number, default: 1 },
})

const emit = defineEmits(['close', 'action'])

const menuStyle = computed(() => {
  const width = 246
  const height = 384
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
const canPublish = computed(() => sources.value.has('data'))
const hasSteamActions = computed(() => hasWorkshop.value || canPublish.value)
const isBatchSelection = computed(() => Number(props.selectionCount) > 1)
const batchLabel = label => (
  isBatchSelection.value ? `${label}（${Number(props.selectionCount)}项）` : label
)
const selectedTypes = computed(() => new Set(
  props.mod?.mod_types?.length ? props.mod.mod_types : [props.mod?.mod_type || 'unknown'],
))

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
    <nav class="context-menu" :class="{ 'submenus-left': submenuToLeft }" :style="menuStyle" role="menu" aria-label="MOD 操作">
      <button type="button" class="context-menu-item" role="menuitem" @click="run('toggle-active')">
        <span class="context-menu-icon">{{ active ? '⊘' : '✓' }}</span>
        <span>{{ batchLabel(active ? '停用' : '启用') }}</span>
      </button>

      <div class="context-menu-parent" data-testid="context-type-menu">
        <span class="context-menu-icon">◆</span>
        <span>{{ batchLabel('修改类型') }}</span>
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
            <span>{{ batchLabel(type.name) }}</span>
          </button>
          <div class="context-menu-divider"></div>
          <button type="button" class="context-menu-item" role="menuitem" @click.stop="run('manage-types')">
            <span class="context-menu-icon">⚙</span>
            <span>类型管理</span>
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
        <span>{{ batchLabel('移动到') }}</span>
        <span v-if="active" class="context-menu-arrow">›</span>
        <span v-else class="context-menu-unavailable">不可用</span>
        <div v-if="active" class="context-submenu" role="menu">
          <button type="button" class="context-menu-item" @click.stop="run('move-specific')">
            <span class="context-menu-icon">#</span><span>{{ batchLabel('指定加载顺序') }}</span>
          </button>
          <button type="button" class="context-menu-item" @click.stop="run('move-top')">
            <span class="context-menu-icon">⇈</span><span>{{ batchLabel('列表顶部') }}</span>
          </button>
          <button type="button" class="context-menu-item" @click.stop="run('move-bottom')">
            <span class="context-menu-icon">⇊</span><span>{{ batchLabel('列表底部') }}</span>
          </button>
        </div>
      </div>

      <div
        class="context-menu-parent"
        :class="{ disabled: !hasSteamActions }"
        :aria-disabled="!hasSteamActions"
        data-testid="context-steam-menu"
      >
        <span class="context-menu-icon steam-icon">S</span>
        <span>{{ batchLabel('Steam 操作') }}</span>
        <span v-if="hasSteamActions" class="context-menu-arrow">›</span>
        <span v-else class="context-menu-unavailable">不可用</span>
        <div v-if="hasSteamActions" class="context-submenu" role="menu">
          <button v-if="hasWorkshop" type="button" class="context-menu-item" @click.stop="run('open-workshop')">
            <span class="context-menu-icon">↗</span><span>{{ batchLabel('访问创意工坊') }}</span>
          </button>
          <button v-if="hasWorkshop" type="button" class="context-menu-item danger-item" @click.stop="run('unsubscribe')">
            <span class="context-menu-icon">⊘</span><span>{{ batchLabel('取消订阅') }}</span>
          </button>
          <button v-if="hasWorkshop" type="button" class="context-menu-item" @click.stop="run('force-update')">
            <span class="context-menu-icon">↻</span><span>{{ batchLabel('强制更新') }}</span>
          </button>
          <div v-if="hasWorkshop && canPublish" class="context-menu-divider"></div>
          <button v-if="canPublish && !hasWorkshop" type="button" class="context-menu-item" @click.stop="run('publish-upload')">
            <span class="context-menu-icon">↑</span><span>{{ batchLabel('上传到工坊') }}</span>
          </button>
          <button v-if="canPublish && hasWorkshop" type="button" class="context-menu-item" @click.stop="run('publish-update')">
            <span class="context-menu-icon">⇧</span><span>{{ batchLabel('更新到工坊') }}</span>
          </button>
        </div>
      </div>

      <div class="context-menu-divider"></div>

      <button type="button" class="context-menu-item" @click="run('open-folder')">
        <span class="context-menu-icon">▣</span>
        <span>{{ batchLabel('打开文件目录') }}</span>
      </button>
      <button
        type="button"
        class="context-menu-item"
        :disabled="isBatchSelection"
        :title="isBatchSelection ? '批量选择时不能在 RPFM 中打开' : ''"
        data-testid="context-open-rpfm"
        @click="run('open-rpfm')"
      >
        <span class="context-menu-icon">R</span>
        <span>在 RPFM 打开</span>
        <span v-if="isBatchSelection" class="context-menu-unavailable">仅限单项</span>
      </button>
      <button type="button" class="context-menu-item" @click="run('toggle-hidden')">
        <span class="context-menu-icon">{{ mod.hidden ? '◉' : '◌' }}</span>
        <span>{{ batchLabel(mod.hidden ? '取消隐藏' : '从列表中隐藏') }}</span>
      </button>
      <button
        type="button"
        class="context-menu-item"
        :disabled="!canCopyToData"
        :title="canCopyToData ? '' : '该 Pack 已存在于 Data 目录'"
        @click="run('copy-to-data')"
      >
        <span class="context-menu-icon">⇩</span>
        <span>{{ batchLabel('复制模组到 Data 文件夹') }}</span>
        <span v-if="!canCopyToData" class="context-menu-unavailable">已在 Data</span>
      </button>
    </nav>
  </div>
</template>
