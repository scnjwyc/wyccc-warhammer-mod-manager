<script setup>
import { reactive, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  types: { type: Array, default: () => [] },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'create', 'update', 'delete'])
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
  if (!window.confirm(`确定删除自定义类型“${type.name}”吗？相关 MOD 将改为“未知”。`)) return
  emit('delete', type.id)
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card type-manager-modal" role="dialog" aria-modal="true" aria-label="类型管理">
      <header class="modal-header">
        <div>
          <span class="eyebrow">MOD CATEGORIES</span>
          <h2>类型管理</h2>
        </div>
        <button type="button" class="icon-button" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <p class="type-manager-help">默认类型不可修改或删除；自定义类型可自由维护。</p>
        <div class="type-manager-list">
          <div v-for="type in types" :key="type.id" class="type-manager-row" :class="{ builtIn: type.built_in }">
            <span v-if="type.built_in" class="type-name-readonly">{{ type.name }}</span>
            <input
              v-else
              v-model="edits[type.id]"
              type="text"
              maxlength="40"
              :aria-label="`修改类型 ${type.name}`"
              @keydown.enter="updateType(type)"
            />
            <span v-if="type.built_in" class="default-type-badge">默认</span>
            <template v-else>
              <button type="button" class="secondary-button compact" :disabled="!!busy" @click="updateType(type)">保存</button>
              <button type="button" class="secondary-button compact danger-text" :disabled="!!busy" @click="deleteType(type)">删除</button>
            </template>
          </div>
        </div>

        <form class="type-create-row" @submit.prevent="createType">
          <input v-model="newTypeName" type="text" maxlength="40" placeholder="输入新的自定义类型名称" />
          <button type="submit" class="primary-button compact" :disabled="!!busy || !newTypeName.trim()">新增类型</button>
        </form>
      </div>

      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">完成</button>
      </footer>
    </section>
  </div>
</template>
