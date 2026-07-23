<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { t } from '../languages'
import { SORT_OPTIONS, sortOptionLabel } from '../modSearch'

const props = defineProps({
  mode: { type: String, default: 'priority' },
  descending: { type: Boolean, default: false },
  testId: { type: String, default: 'sort-button' },
})

const emit = defineEmits(['update:mode', 'update:descending'])
const root = ref(null)
const open = ref(false)
const currentLabel = computed(() => sortOptionLabel(SORT_OPTIONS.find(option => option.id === props.mode)))

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
      :title="t('search.displaySortTitle', { label: currentLabel })"
      :data-testid="testId"
      @click="open = !open"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7h11M4 12h8M4 17h5M18 5v14m0 0-3-3m3 3 3-3"></path>
      </svg>
    </button>
    <div v-if="open" class="sort-menu" role="menu" data-testid="sort-menu">
      <strong>{{ t('search.displaySort') }}</strong>
      <button
        v-for="option in SORT_OPTIONS"
        :key="option.id"
        type="button"
        :class="{ selected: mode === option.id }"
        @click="choose(option)"
      >
        <span>{{ mode === option.id ? '✓' : '' }}</span>
        {{ sortOptionLabel(option) }}
      </button>
      <div class="sort-menu-divider"></div>
      <button
        type="button"
        :disabled="mode === 'priority'"
        @click="emit('update:descending', !descending)"
      >
        <span>↕</span>
        {{ descending ? t('search.descending') : t('search.ascending') }}
      </button>
      <p>{{ t('search.displayOnly') }}</p>
    </div>
  </div>
</template>
