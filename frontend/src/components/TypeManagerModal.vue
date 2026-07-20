<script setup>
import { reactive, ref, watch } from 'vue'
import { localizedModTypeName, t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  types: { type: Array, default: () => [] },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'create', 'update', 'delete', 'move'])
const newTypeName = ref('')
const edits = reactive({})

watch(
  () => [props.open, props.types],
  () => {
    for (const key of Object.keys(edits)) delete edits[key]
    for (const type of props.types) edits[type.id] = type.name
    if (!props.open) newTypeName.value = ''
  },
  { immediate: true, deep: true },
)

const createType = () => {
  if (props.busy) return
  const name = newTypeName.value.trim()
  if (!name) return
  emit('create', name)
  newTypeName.value = ''
}

const updateType = type => {
  if (props.busy) return
  const name = String(edits[type.id] || '').trim()
  if (!name || name === type.name) return
  emit('update', { id: type.id, name })
}

const deleteType = type => {
  if (props.busy) return
  if (!window.confirm(t('types.deleteConfirm', { name: type.name, unknown: t('modType.unknown') }))) return
  emit('delete', type.id)
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card type-manager-modal" role="dialog" aria-modal="true" :aria-label="t('types.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('types.eyebrow') }}</span>
          <h2>{{ t('types.aria') }}</h2>
        </div>
        <button type="button" class="icon-button" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <p class="type-manager-help">{{ t('types.help') }}</p>
        <div class="type-manager-list">
          <div v-for="(type, index) in types" :key="type.id" class="type-manager-row" :class="{ builtIn: type.built_in }">
            <span v-if="type.built_in" class="type-name-readonly">{{ localizedModTypeName(type) }}</span>
            <input
              v-else
              v-model="edits[type.id]"
              type="text"
              maxlength="40"
              :aria-label="t('types.editAria', { name: type.name })"
              @keydown.enter="updateType(type)"
            />
            <span v-if="type.built_in" class="default-type-badge">{{ t('common.default') }}</span>
            <template v-else>
              <button type="button" class="secondary-button compact" :disabled="!!busy" @click="updateType(type)">{{ t('common.save') }}</button>
              <button type="button" class="secondary-button compact danger-text" :disabled="!!busy" @click="deleteType(type)">{{ t('common.delete') }}</button>
            </template>
            <span class="type-manager-order-actions">
              <button
                type="button"
                class="icon-button"
                :disabled="!!busy || index === 0"
                :title="t('list.moveUp')"
                :aria-label="`${t('list.moveUp')} ${localizedModTypeName(type)}`"
                :data-testid="`type-move-up-${type.id}`"
                @click="emit('move', { id: type.id, direction: -1 })"
              >&uarr;</button>
              <button
                type="button"
                class="icon-button"
                :disabled="!!busy || index === types.length - 1"
                :title="t('list.moveDown')"
                :aria-label="`${t('list.moveDown')} ${localizedModTypeName(type)}`"
                :data-testid="`type-move-down-${type.id}`"
                @click="emit('move', { id: type.id, direction: 1 })"
              >&darr;</button>
            </span>
          </div>
        </div>

        <form class="type-create-row" @submit.prevent="createType">
          <input v-model="newTypeName" type="text" maxlength="40" :placeholder="t('types.newPlaceholder')" />
          <button type="submit" class="primary-button compact" :disabled="!!busy || !newTypeName.trim()">{{ t('types.add') }}</button>
        </form>
      </div>

      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">{{ t('common.done') }}</button>
      </footer>
    </section>
  </div>
</template>
