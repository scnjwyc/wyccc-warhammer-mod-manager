<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  saves: { type: Array, default: () => [] },
  directory: { type: String, default: '' },
  busy: { type: String, default: '' },
  running: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'refresh', 'load'])
const query = ref('')

watch(() => props.open, open => {
  if (open) query.value = ''
})

const filteredSaves = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  if (!needle) return props.saves
  return props.saves.filter(save => save.name.toLocaleLowerCase().includes(needle))
})

const formatDate = value => new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
}).format(new Date(Number(value || 0)))

const formatSize = value => {
  const bytes = Number(value || 0)
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card save-games-modal" role="dialog" aria-modal="true" aria-label="战役存档">
      <header class="modal-header">
        <div>
          <span class="eyebrow">CAMPAIGN SAVES</span>
          <h2>从指定存档载入</h2>
        </div>
        <button type="button" class="icon-button" @click="emit('close')">×</button>
      </header>

      <div class="save-games-toolbar">
        <input v-model="query" type="search" placeholder="搜索存档名称" aria-label="搜索存档名称" />
        <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('refresh')">刷新</button>
      </div>

      <div class="save-games-directory" :title="directory">{{ directory || '未找到存档目录' }}</div>

      <div class="save-games-list">
        <article v-for="save in filteredSaves" :key="save.path" class="save-game-row">
          <div>
            <strong :title="save.name">{{ save.name }}</strong>
            <span>{{ formatDate(save.modified_at) }} · {{ formatSize(save.size) }}</span>
          </div>
          <button
            type="button"
            class="primary-button"
            :disabled="!!busy || running"
            @click="emit('load', save.name)"
          >载入</button>
        </article>
        <div v-if="!filteredSaves.length" class="empty-state save-games-empty">
          <p>{{ saves.length ? '没有符合搜索条件的存档' : '没有找到战役存档' }}</p>
        </div>
      </div>

      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">关闭</button>
      </footer>
    </section>
  </div>
</template>
