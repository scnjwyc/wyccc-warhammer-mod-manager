<script setup>
import { computed } from 'vue'
import { currentLocale, t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  comparison: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const groups = computed(() => [
  { id: 'added', key: 'launchComparison.added', items: props.comparison?.added || [] },
  { id: 'removed', key: 'launchComparison.removed', items: props.comparison?.removed || [] },
  { id: 'shared', key: 'launchComparison.shared', items: props.comparison?.shared || [] },
])
const launchTime = computed(() => props.comparison?.startedAt
  ? new Date(props.comparison.startedAt * 1000).toLocaleString(currentLocale()) : '')
</script>

<template>
  <div v-if="open && comparison" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card save-mods-comparison-modal" role="dialog" aria-modal="true" :aria-label="t('launchComparison.title')">
      <header class="modal-header">
        <div>
          <h2>{{ t('launchComparison.title') }}</h2>
          <small v-if="comparison.available">{{ t('launchComparison.time', { time: launchTime }) }}</small>
        </div>
        <button type="button" class="icon-button" :aria-label="t('common.close')" @click="emit('close')">×</button>
      </header>
      <p v-if="!comparison.available" class="launch-comparison-summary" data-testid="no-launch-record">{{ t('launchComparison.noRecord') }}</p>
      <template v-else>
        <p class="launch-comparison-summary" data-testid="launch-comparison-summary">
          {{ comparison.identical ? t('launchComparison.identical') : t('launchComparison.summary', {
            added: comparison.added.length, removed: comparison.removed.length, reordered: comparison.reorderedCount,
          }) }}
        </p>
        <div class="save-mods-comparison-grid">
          <section v-for="group in groups" :key="group.id" class="save-mods-comparison-group" :data-testid="`${group.id}-group`">
            <h3>{{ t(group.key) }} <span>{{ group.items.length }}</span></h3>
            <div class="save-mods-comparison-list">
              <article v-for="item in group.items" :key="item.packName">
                <strong>{{ item.mod?.effective_name || item.mod?.display_name || t('launchHistory.unknownMod') }}</strong>
                <small v-if="item.reordered" class="launch-order-change">{{ item.previousPosition === item.currentPosition
                  ? t('launchComparison.relativeOrder')
                  : t('launchComparison.position', { before: item.previousPosition, after: item.currentPosition }) }}</small>
              </article>
              <p v-if="!group.items.length" class="empty-changelog">{{ t('saves.compareEmpty') }}</p>
            </div>
          </section>
        </div>
      </template>
      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>
