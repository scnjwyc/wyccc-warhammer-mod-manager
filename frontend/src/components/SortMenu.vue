<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { SORT_OPTIONS } from '../modSearch'

const props = defineProps({
  mode: { type: String, default: 'priority' },
  descending: { type: Boolean, default: false },
})

const emit = defineEmits(['update:mode', 'update:descending'])
const root = ref(null)
const open = ref(false)
const currentLabel = computed(() => SORT_OPTIONS.find(option => option.id === props.mode)?.label || '优先级')

const choose = option => {
  emit('update:mode', option.id)
  open.value = false
}

const closeOutside = event => {
  if (open.value && root.value && !root.value.contains(event.target)) open.value = false
}

onMounted(() => window.addEventListener('mousedown', closeOutside))
onBeforeUnmount(() => window.removeEventListener('mousedown', closeOutside))
</script>

<template>
  <div ref="root" class="sort-control">
    <button
      type="button"
      class="sort-button"
      :class="{ active: mode !== 'priority' }"
      :aria-expanded="open"
      :title="`列表显示排序：${currentLabel}`"
      data-testid="sort-button"
      @click="open = !open"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7h11M4 12h8M4 17h5M18 5v14m0 0-3-3m3 3 3-3"></path>
      </svg>
    </button>
    <div v-if="open" class="sort-menu" role="menu" data-testid="sort-menu">
      <strong>列表显示排序</strong>
      <button
        v-for="option in SORT_OPTIONS"
        :key="option.id"
        type="button"
        :class="{ selected: mode === option.id }"
        @click="choose(option)"
      >
        <span>{{ mode === option.id ? '✓' : '' }}</span>
        {{ option.label }}
      </button>
      <div class="sort-menu-divider"></div>
      <button
        type="button"
        :disabled="mode === 'priority'"
        @click="emit('update:descending', !descending)"
      >
        <span>↕</span>
        {{ descending ? '降序' : '升序' }}
      </button>
      <p>仅改变列表显示，不修改实际加载顺序。</p>
    </div>
  </div>
</template>
