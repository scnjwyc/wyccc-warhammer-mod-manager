<script setup>
import { computed, ref, watch } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  preview: { type: Object, default: null },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'import'])
const subscribeMissing = ref(true)

watch(() => props.open, open => {
  if (open) subscribeMissing.value = true
})

const missing = computed(() => props.preview?.missing || [])
const unsubscribed = computed(() => props.preview?.unsubscribed || [])
const installedCount = computed(() => props.preview?.ordered_mod_ids?.length || 0)
const importProfile = mode => emit('import', { mode, subscribeMissing: subscribeMissing.value })
</script>

<template>
  <div v-if="open && preview" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card official-profile-modal" role="dialog" aria-modal="true" :aria-label="t('official.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('official.eyebrow') }}</span>
          <h2>{{ t('official.title') }}</h2>
          <small :title="preview.profile.path">{{ preview.profile.name }}</small>
        </div>
        <button type="button" class="icon-button" :disabled="!!busy" @click="emit('close')">×</button>
      </header>

      <div class="modal-body official-profile-body">
        <div class="official-profile-summary">
          <article><strong>{{ installedCount }}</strong><span>{{ t('official.installed') }}</span></article>
          <article><strong>{{ missing.length }}</strong><span>{{ t('official.missing') }}</span></article>
          <article><strong>{{ preview.unrecognized_lines?.length || 0 }}</strong><span>{{ t('official.unrecognized') }}</span></article>
        </div>

        <div v-if="missing.length" class="official-profile-missing-list">
          <h3>{{ t('official.missingTitle') }}</h3>
          <article v-for="item in missing" :key="`${item.workshop_id}:${item.pack_name}`">
            <strong>{{ unsubscribed.find(entry => entry.workshop_id === item.workshop_id)?.title || item.pack_name }}</strong>
            <small>Workshop #{{ item.workshop_id }} · {{ item.pack_name }}</small>
          </article>
        </div>

        <label v-if="unsubscribed.length" class="switch-row official-subscribe-row">
          <input v-model="subscribeMissing" type="checkbox" data-testid="official-subscribe-missing" />
          <span><strong>{{ t('official.subscribeMissing') }}</strong><small>{{ t('official.subscribeMissingHelp', { count: unsubscribed.length }) }}</small></span>
        </label>

        <p class="settings-page-note">{{ t('official.pendingHelp') }}</p>
      </div>

      <footer class="modal-footer official-profile-footer">
        <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">{{ t('common.cancel') }}</button>
        <span class="footer-spacer"></span>
        <button
          type="button"
          class="secondary-button"
          data-testid="official-import-replace"
          :disabled="!!busy"
          @click="importProfile('replace')"
        >{{ t('official.replaceCurrent') }}</button>
        <button
          type="button"
          class="primary-button"
          data-testid="official-import-new"
          :disabled="!!busy"
          @click="importProfile('new')"
        >{{ t('official.createNew') }}</button>
      </footer>
    </section>
  </div>
</template>
