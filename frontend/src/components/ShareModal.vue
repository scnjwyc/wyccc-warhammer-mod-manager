<script setup>
import { ref, watch } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  exportValue: { type: String, default: '' },
  busy: { type: String, default: '' },
  canImportOfficialProfile: { type: Boolean, default: true },
})

const emit = defineEmits([
  'close',
  'export',
  'import',
  'import-collection',
  'import-official',
  'export-json',
  'import-json',
])
const value = ref('')
const collectionValue = ref('')
const includeDescriptions = ref(false)
const importMode = ref('new')

watch(
  () => props.exportValue,
  next => {
    if (next) value.value = next
  },
)

const copyValue = async () => {
  if (value.value) await navigator.clipboard.writeText(value.value)
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card share-modal" role="dialog" aria-modal="true" :aria-label="t('share.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('share.eyebrow') }}</span>
          <h2>{{ t('share.title') }}</h2>
        </div>
        <button type="button" class="icon-button" @click="emit('close')">×</button>
      </header>
      <div class="modal-body">
        <p class="muted-copy">
          {{ t('share.help') }}
        </p>
        <textarea
          v-model="value"
          class="share-textarea"
          rows="10"
          :placeholder="t('share.placeholder')"
        ></textarea>
        <div class="share-collection-import">
          <label class="field-label" for="share-collection-input">
            <span>{{ t('share.collectionInput') }}</span>
          </label>
          <div class="share-collection-controls">
            <input
              id="share-collection-input"
              v-model="collectionValue"
              type="text"
              data-testid="share-collection-input"
              :placeholder="t('share.collectionPlaceholder')"
            />
            <button
              type="button"
              class="secondary-button"
              :disabled="!!busy || !collectionValue.trim()"
              data-testid="share-import-collection"
              @click="emit('import-collection', collectionValue)"
            >
              {{ t('share.importCollection') }}
            </button>
          </div>
          <small class="field-help">{{ t('share.collectionHelp') }}</small>
        </div>
        <div class="share-json">
          <label class="field-label">
            <span>{{ t('share.jsonSection') }}</span>
          </label>
          <p class="muted-copy">{{ t('share.jsonHelp') }}</p>
          <div class="share-json-controls">
            <label class="share-json-check">
              <input v-model="includeDescriptions" type="checkbox" :disabled="!!busy" />
              {{ t('share.includeDescriptions') }}
            </label>
            <button
              type="button"
              class="secondary-button"
              :disabled="!!busy"
              data-testid="share-export-json"
              @click="emit('export-json', includeDescriptions)"
            >
              {{ t('share.exportJson') }}
            </button>
          </div>
          <div class="share-json-controls">
            <label class="share-json-mode">
              <span>{{ t('share.importMode') }}</span>
              <select v-model="importMode" :disabled="!!busy">
                <option value="new">{{ t('share.importModeNew') }}</option>
                <option value="current">{{ t('share.importModeCurrent') }}</option>
              </select>
            </label>
            <button
              type="button"
              class="secondary-button"
              :disabled="!!busy"
              data-testid="share-import-json"
              @click="emit('import-json', importMode)"
            >
              {{ t('share.importJson') }}
            </button>
          </div>
        </div>
        <div class="button-row">
          <button
            v-if="canImportOfficialProfile"
            type="button"
            class="secondary-button"
            :disabled="!!busy"
            data-testid="share-import-official"
            @click="emit('import-official')"
          >
            {{ t('share.importOfficial') }}
          </button>
          <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('export')">
            {{ t('share.generate') }}
          </button>
          <button type="button" class="secondary-button" :disabled="!value" @click="copyValue">
            {{ t('common.copy') }}
          </button>
          <button type="button" class="primary-button" :disabled="!!busy || !value" @click="emit('import', value)">
            {{ t('share.importCurrent') }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.share-json {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.share-json-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.share-json-check,
.share-json-mode {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.share-json-mode select {
  height: 32px;
  padding: 0 8px;
}
</style>
