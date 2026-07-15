<script setup>
import { reactive, watch } from 'vue'

import { useAppStore } from '../store'

const props = defineProps({
  open: { type: Boolean, default: false },
  mode: { type: String, default: 'upload' },
  mod: { type: Object, default: null },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'submit'])
const store = useAppStore()
const draft = reactive({
  title: '',
  description: '',
  change_note: '',
  preview_path: '',
  category: 'graphical',
  visibility: 0,
  confirmed: false,
})

const categories = [
  ['graphical', '美化 / Graphical'],
  ['campaign', '战役 / Campaign'],
  ['units', '单位 / Units'],
  ['battle', '战斗 / Battle'],
  ['ui', '界面 / UI'],
  ['maps', '地图 / Maps'],
  ['overhaul', '大修 / Overhaul'],
  ['compilation', '合集 / Compilation'],
  ['cheat', '修改 / Cheat'],
]

watch(
  () => [props.open, props.mod?.id, props.mode],
  () => {
    if (!props.open || !props.mod) return
    draft.title = props.mod.effective_name || props.mod.display_name || props.mod.pack_name || ''
    draft.description = props.mod.description || ''
    draft.change_note = props.mode === 'update' ? '内容更新' : ''
    draft.preview_path = props.mod.preview_path || ''
    draft.category = 'graphical'
    draft.visibility = 0
    draft.confirmed = false
  },
  { immediate: true },
)

const browsePreview = async () => {
  const result = await store.selectDirectory('preview')
  if (result.path) draft.preview_path = result.path
}

const submit = () => {
  if (!draft.confirmed || !draft.title.trim() || !draft.preview_path.trim()) return
  emit('submit', {
    mode: props.mode,
    title: draft.title.trim(),
    description: draft.description,
    change_note: draft.change_note,
    preview_path: draft.preview_path.trim(),
    category: draft.category,
    visibility: Number(draft.visibility),
  })
}
</script>

<template>
  <div v-if="open && mod" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card workshop-publish-modal" role="dialog" aria-modal="true" aria-label="Workshop 发布">
      <header class="modal-header">
        <div>
          <span class="eyebrow">STEAM WORKSHOP</span>
          <h2>{{ mode === 'upload' ? '上传到工坊' : '更新到工坊' }}</h2>
        </div>
        <button type="button" class="close-button" :disabled="!!busy" @click="emit('close')">×</button>
      </header>

      <div class="modal-body publish-form">
        <p class="publish-pack-path" :title="mod.path">{{ mod.pack_name }} · {{ mod.path }}</p>
        <label v-if="mode === 'update'" class="field-label">
          <span>Workshop ID</span>
          <input :value="mod.workshop_id" type="text" readonly />
        </label>
        <label class="field-label">
          <span>标题</span>
          <input v-model="draft.title" type="text" maxlength="128" />
        </label>
        <label class="field-label">
          <span>描述</span>
          <textarea v-model="draft.description" rows="6" maxlength="8000"></textarea>
        </label>
        <label v-if="mode === 'update'" class="field-label">
          <span>更新说明</span>
          <textarea v-model="draft.change_note" rows="3" maxlength="8000"></textarea>
        </label>
        <label class="field-label">
          <span>预览图（PNG/JPEG，最大 1 MB）</span>
          <div class="path-input-row">
            <input v-model="draft.preview_path" type="text" />
            <button type="button" class="secondary-button" @click="browsePreview">浏览</button>
          </div>
        </label>
        <div class="publish-grid">
          <label class="field-label">
            <span>分类标签</span>
            <select v-model="draft.category">
              <option v-for="category in categories" :key="category[0]" :value="category[0]">{{ category[1] }}</option>
            </select>
          </label>
          <label class="field-label">
            <span>可见性</span>
            <select v-model="draft.visibility">
              <option :value="0">公开</option>
              <option :value="1">仅好友</option>
              <option :value="2">私密</option>
              <option :value="3">不公开列出</option>
            </select>
          </label>
        </div>
        <label class="publish-confirmation">
          <input v-model="draft.confirmed" type="checkbox" />
          <span>
            {{ mode === 'upload'
              ? '我确认要使用当前 Steam 账号创建新的 Workshop 项目。'
              : '我确认当前 Steam 账号拥有该 Workshop 项目；程序会在提交前再次验证所有权。' }}
          </span>
        </label>
      </div>

      <footer class="modal-footer">
        <span class="publish-warning">提交期间请保持 Steam 在线并关闭 Warhammer III。</span>
        <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">取消</button>
        <button
          type="button"
          class="primary-button"
          :disabled="!!busy || !draft.confirmed || !draft.title.trim() || !draft.preview_path.trim()"
          @click="submit"
        >
          {{ busy || (mode === 'upload' ? '创建并上传' : '提交更新') }}
        </button>
      </footer>
    </section>
  </div>
</template>
