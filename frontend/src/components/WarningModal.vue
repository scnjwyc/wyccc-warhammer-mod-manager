<script setup>
import { computed } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'select', 'ignore'])

const ignorableCount = computed(() => props.items.filter(item => item.ignorable).length)

const typeLabel = item => ({
  mod_newer_than_game: 'MOD 过期',
  missing_dependency: '缺失依赖',
}[item.code] || '扫描提示')
</script>

<template>
  <div v-if="open" class="modal-backdrop warning-modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card warning-modal" role="dialog" aria-modal="true" aria-label="MOD 警告">
      <header class="modal-header">
        <div>
          <span class="eyebrow">MOD WARNINGS</span>
          <h2>问题与警告</h2>
        </div>
        <button type="button" class="icon-button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div v-if="items.length" class="warning-modal-summary">
        <strong>共 {{ items.length }} 条警告</strong>
        <span>其中 {{ ignorableCount }} 条 MOD 问题可逐条忽略。</span>
      </div>

      <div class="warning-modal-list">
        <article
          v-for="item in items"
          :key="item.id"
          class="warning-modal-row"
          :class="`severity-${item.severity}`"
        >
          <button
            v-if="item.modId"
            type="button"
            class="warning-modal-copy"
            :title="`在列表中选择 ${item.modName}`"
            @click="emit('select', item)"
          >
            <span class="warning-modal-type">{{ typeLabel(item) }}</span>
            <strong>{{ item.modName }}</strong>
            <small>{{ item.message }}</small>
          </button>
          <div v-else class="warning-modal-copy system-warning-copy">
            <span class="warning-modal-type">{{ typeLabel(item) }}</span>
            <strong>扫描提示</strong>
            <small>{{ item.message }}</small>
          </div>
          <button
            v-if="item.ignorable"
            type="button"
            class="warning-ignore-button"
            :disabled="!!busy"
            @click="emit('ignore', item)"
          >
            忽略
          </button>
          <span v-else class="warning-system-label">系统</span>
        </article>

        <div v-if="!items.length" class="warning-modal-empty">
          <span>✓</span>
          <strong>当前没有未忽略的问题</strong>
        </div>
      </div>

      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">关闭</button>
      </footer>
    </section>
  </div>
</template>
