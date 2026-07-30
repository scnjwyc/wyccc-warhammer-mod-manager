<script setup>
import { nextTick, ref, watch } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  message: { type: String, default: '' },
  confirmLabel: { type: String, default: '' },
  danger: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'confirm'])
const confirmButton = ref(null)

watch(
  () => props.open,
  async open => {
    if (!open) return
    await nextTick()
    confirmButton.value?.focus()
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop confirmation-backdrop" @mousedown.self="emit('close')">
      <section
        class="modal-card confirmation-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirmation-modal-title"
        aria-describedby="confirmation-modal-message"
      >
        <header class="modal-header">
          <div>
            <span class="eyebrow">{{ t('confirmation.eyebrow') }}</span>
            <h2 id="confirmation-modal-title">{{ title || t('confirmation.title') }}</h2>
          </div>
          <button type="button" class="icon-button" :aria-label="t('common.close')" @click="emit('close')">×</button>
        </header>

        <div class="modal-body confirmation-modal-body">
          <p id="confirmation-modal-message" class="confirmation-message">{{ message }}</p>
        </div>

        <footer class="modal-footer confirmation-modal-footer">
          <button type="button" class="secondary-button" @click="emit('close')">{{ t('common.cancel') }}</button>
          <button
            ref="confirmButton"
            type="button"
            :class="danger ? 'danger-button' : 'primary-button'"
            data-testid="confirmation-confirm"
            @click="emit('confirm')"
          >{{ confirmLabel || t('common.confirm') }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
