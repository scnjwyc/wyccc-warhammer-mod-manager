<script setup>
import { computed } from 'vue'
import { localizeBackendMessage, t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'select', 'ignore', 'subscribe-enable'])

const ignorableCount = computed(() => props.items.filter(item => item.ignorable).length)

const typeLabel = item => ({
  outdated_mod: t('app.warningOutdated'),
  missing_dependency: t('app.warningMissingDependency'),
  workshop_dependency_refresh: t('warnings.workshopDependencyTitle'),
}[item.code] || t('warnings.scanNotice'))

const warningMessage = item => localizeBackendMessage(item.message, 'warnings.genericScan')
const canSubscribeAndEnable = item => (
  item.code === 'missing_dependency'
  && item.dependencies?.some(dependency => (
    dependency?.kind === 'workshop' || dependency?.availability === 'disabled'
  ))
)
</script>

<template>
  <div v-if="open" class="modal-backdrop warning-modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card warning-modal" role="dialog" aria-modal="true" :aria-label="t('warnings.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('warnings.eyebrow') }}</span>
          <h2>{{ t('warnings.title') }}</h2>
        </div>
        <button type="button" class="icon-button" :aria-label="t('common.close')" @click="emit('close')">×</button>
      </header>

      <div v-if="items.length" class="warning-modal-summary">
        <strong>{{ t('warnings.total', { count: items.length }) }}</strong>
        <span>{{ t('warnings.ignorable', { count: ignorableCount }) }}</span>
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
            :title="t('warnings.selectMod', { name: item.modName })"
            @click="emit('select', item)"
          >
            <span class="warning-modal-type">{{ typeLabel(item) }}</span>
            <strong>{{ item.modName }}</strong>
            <small>{{ warningMessage(item) }}</small>
          </button>
          <div v-else class="warning-modal-copy system-warning-copy">
            <span class="warning-modal-type">{{ typeLabel(item) }}</span>
            <strong>{{ t('warnings.scanNotice') }}</strong>
            <small>{{ warningMessage(item) }}</small>
          </div>
          <div class="warning-row-actions">
            <button
              v-if="canSubscribeAndEnable(item)"
              type="button"
              class="warning-subscribe-button"
              :disabled="!!busy"
              @click="emit('subscribe-enable', item)"
            >
              {{ t('warnings.subscribeEnableDependencies') }}
            </button>
            <button
              v-if="item.ignorable"
              type="button"
              class="warning-ignore-button"
              :disabled="!!busy"
              @click="emit('ignore', item)"
            >
              {{ t('common.ignore') }}
            </button>
            <span v-else-if="item.code !== 'missing_dependency'" class="warning-system-label">{{ t('common.system') }}</span>
          </div>
        </article>

        <div v-if="!items.length" class="warning-modal-empty">
          <span>✓</span>
          <strong>{{ t('warnings.none') }}</strong>
        </div>
      </div>

      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>
