<script setup>
import { computed } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  comparison: { type: Object, default: null },
})

const emit = defineEmits(['close'])

const groups = computed(() => [
  { id: 'save-only', key: 'saves.compareSaveOnly', items: props.comparison?.saveOnly || [] },
  { id: 'current-only', key: 'saves.compareCurrentOnly', items: props.comparison?.currentOnly || [] },
  { id: 'shared', key: 'saves.compareShared', items: props.comparison?.shared || [] },
])
</script>

<template>
  <div v-if="open && comparison" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card save-mods-comparison-modal" role="dialog" aria-modal="true" :aria-label="t('saves.compareTitle')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('saves.compareEyebrow') }}</span>
          <h2>{{ t('saves.compareTitle') }}</h2>
          <small>{{ comparison.save?.name || '' }}</small>
        </div>
        <button type="button" class="icon-button" @click="emit('close')">×</button>
      </header>
      <div class="save-mods-comparison-grid">
        <section
          v-for="group in groups"
          :key="group.id"
          class="save-mods-comparison-group"
          :data-testid="`${group.id}-group`"
        >
          <h3>{{ t(group.key) }} <span>{{ group.items.length }}</span></h3>
          <div class="save-mods-comparison-list">
            <article v-for="item in group.items" :key="item.packName">
              <strong>{{ item.mod?.effective_name || item.packName }}</strong>
              <small v-if="item.mod?.effective_name">{{ item.packName }}</small>
            </article>
            <p v-if="!group.items.length" class="empty-changelog">{{ t('saves.compareEmpty') }}</p>
          </div>
        </section>
      </div>
      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>
