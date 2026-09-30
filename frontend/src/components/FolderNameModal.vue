<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  rename: { type: Boolean, default: false },
  initialName: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['close', 'submit'])
const name = ref('')
const nameInput = ref(null)
const dialog = ref(null)
const validName = computed(() => {
  const length = [...name.value.trim()].length
  return length > 0 && length <= 80
})
const close = () => { if (!props.busy) emit('close') }
const submit = () => {
  if (validName.value && !props.busy) emit('submit', name.value.trim())
}
const onKeydown = event => {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    close()
  } else if (event.key === 'Tab') {
    const elements = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled)')]
    const first = elements[0]
    const last = elements.at(-1)
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }
}
watch(() => props.open, async open => {
  if (!open) return
  name.value = props.initialName
  await nextTick()
  nameInput.value?.focus()
  nameInput.value?.select()
}, { immediate: true })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @mousedown.self="close">
      <form ref="dialog" class="modal-card folder-name-modal" role="dialog" aria-modal="true"
        :aria-label="rename ? t('folders.rename') : t('folders.create')"
        @submit.prevent="submit" @keydown="onKeydown">
        <header class="modal-header">
          <h2>{{ rename ? t('folders.rename') : t('folders.create') }}</h2>
          <button type="button" class="icon-button" :disabled="busy" :aria-label="t('common.close')" @click="close">×</button>
        </header>
        <div class="modal-body">
          <label class="field-label" for="mod-folder-name">{{ t('folders.name') }}</label>
          <input id="mod-folder-name" ref="nameInput" v-model="name" type="text" autocomplete="off"
            :disabled="busy" :aria-invalid="!validName && !!name" aria-describedby="mod-folder-name-help"
            data-testid="folder-name-input" />
          <p id="mod-folder-name-help" class="folder-name-help">{{ t('folders.promptCreate') }}</p>
          <p v-if="error" class="folder-name-error" role="alert">{{ error }}</p>
        </div>
        <footer class="modal-footer">
          <button type="button" class="secondary-button" :disabled="busy" @click="close">{{ t('common.cancel') }}</button>
          <button type="submit" class="primary-button" :disabled="busy || !validName" data-testid="folder-name-submit">
            {{ t('common.confirm') }}
          </button>
        </footer>
      </form>
    </div>
  </Teleport>
</template>
