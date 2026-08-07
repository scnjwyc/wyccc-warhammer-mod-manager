<script setup>
import { reactive, watch } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  settings: { type: Object, default: () => ({}) },
  busy: { type: String, default: '' },
  requiredPacksEnabled: { type: Boolean, default: true },
  missingPacks: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'save'])

const draft = reactive({
  dynamic_ror_compatibility_patch_enabled: false,
})

const resetDraft = () => {
  draft.dynamic_ror_compatibility_patch_enabled = !!(
    props.settings.dynamic_ror_compatibility_patch_enabled
  )
}

watch(
  () => props.open,
  open => {
    if (open) resetDraft()
  },
  { immediate: true },
)

watch(
  () => props.settings,
  () => {
    if (props.open) resetDraft()
  },
  { deep: true },
)

const currentSettings = () => ({
  dynamic_ror_compatibility_patch_enabled:
    !!draft.dynamic_ror_compatibility_patch_enabled,
})

const submit = () => {
  if (!props.requiredPacksEnabled) return
  emit('save', currentSettings())
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <form
      class="modal-card compatibility-patch-modal"
      role="dialog"
      aria-modal="true"
      :aria-label="t('compatibilityPatch.aria')"
      @submit.prevent="submit"
    >
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('compatibilityPatch.eyebrow') }}</span>
          <h2>{{ t('compatibilityPatch.title') }}</h2>
        </div>
        <button
          type="button"
          class="icon-button"
          :aria-label="t('common.close')"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <div class="modal-body compatibility-patch-body">
        <section class="compatibility-patch-card">
          <label class="switch-row compatibility-patch-option">
            <input
              v-model="draft.dynamic_ror_compatibility_patch_enabled"
              type="checkbox"
              :disabled="!!busy || !requiredPacksEnabled"
              data-testid="dynamic-ror-compatibility-patch-enabled"
            />
            <span>
              <strong>{{ t('compatibilityPatch.dynamicRorTitle') }}</strong>
              <small>{{ t('compatibilityPatch.dynamicRorDescription') }}</small>
            </span>
          </label>
          <p
            v-if="!requiredPacksEnabled"
            class="compatibility-patch-requirement"
            data-testid="dynamic-ror-required-packs"
          >
            {{ t('compatibilityPatch.requiredPacksMissing', { mods: missingPacks.join(', ') }) }}
          </p>
          <p class="compatibility-patch-note">
            {{ t('compatibilityPatch.runtimeNote') }}
          </p>
        </section>
      </div>

      <footer class="modal-footer compatibility-patch-footer">
        <span v-if="busy" class="modal-busy">{{ busy }}</span>
        <button
          type="button"
          class="secondary-button"
          :disabled="!!busy"
          @click="emit('close')"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          type="submit"
          class="primary-button"
          :disabled="!!busy"
          data-testid="compatibility-patch-save"
        >
          {{ t('common.save') }}
        </button>
      </footer>
    </form>
  </div>
</template>

<style scoped>
.compatibility-patch-modal {
  max-width: 560px;
}

.compatibility-patch-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.compatibility-patch-card {
  padding: 18px 18px;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.09));
  border-radius: 10px;
  background: var(--surface, rgba(255, 255, 255, 0.03));
}

.compatibility-patch-option {
  align-items: flex-start;
}

.compatibility-patch-option strong {
  display: block;
  margin-bottom: 6px;
  color: var(--text-primary, #e8e4dc);
  font-size: 15px;
  line-height: 1.35;
}

.compatibility-patch-option small {
  color: var(--text-secondary, #9aa4b2);
  font-size: 12.5px;
  line-height: 1.55;
}

.compatibility-patch-requirement {
  margin: 12px 0 0;
  padding-top: 10px;
  border-top: 1px dashed var(--border, rgba(255, 255, 255, 0.09));
  color: #d69b65;
  font-size: 12.5px;
  line-height: 1.5;
}

.compatibility-patch-note {
  margin: 10px 0 0;
  padding-top: 10px;
  border-top: 1px dashed var(--border, rgba(255, 255, 255, 0.09));
  color: var(--text-secondary, #9aa4b2);
  font-size: 12px;
  line-height: 1.5;
}

.compatibility-patch-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 9px;
}
</style>
