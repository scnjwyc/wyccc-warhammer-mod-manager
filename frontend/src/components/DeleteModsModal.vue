<script setup>
import { t } from '../languages'

defineProps({
  open: { type: Boolean, default: false },
  preview: { type: Object, default: null },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'confirm'])
</script>

<template>
  <div v-if="open && preview" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card delete-mods-modal" role="dialog" aria-modal="true" :aria-label="t('delete.aria')">
      <header class="modal-header">
        <div><span class="eyebrow">{{ t('delete.eyebrow') }}</span><h2>{{ t('delete.title') }}</h2></div>
        <button type="button" class="icon-button" :disabled="!!busy" @click="emit('close')">×</button>
      </header>
      <div class="modal-body delete-mods-body">
        <p>{{ t('delete.summary', { data: preview.data_count, workshop: preview.workshop_count }) }}</p>
        <p class="danger-copy">{{ t('delete.recycleHelp') }}</p>
        <div class="delete-mod-targets">
          <article v-for="target in preview.targets" :key="target.path">
            <span class="source-badge" :class="`source-${target.source}`">{{ target.source.toUpperCase() }}</span>
            <div><strong>{{ target.pack_name }}</strong><code>{{ target.path }}</code></div>
          </article>
        </div>
      </div>
      <footer class="modal-footer">
        <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">{{ t('common.cancel') }}</button>
        <button
          type="button"
          class="danger-button"
          data-testid="confirm-delete-mods"
          :disabled="!!busy"
          @click="emit('confirm', preview.token)"
        >{{ t('delete.confirm') }}</button>
      </footer>
    </section>
  </div>
</template>
