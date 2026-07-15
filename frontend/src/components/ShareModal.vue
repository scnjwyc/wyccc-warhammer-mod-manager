<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  exportValue: { type: String, default: '' },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'export', 'import'])
const value = ref('')

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
    <section class="modal-card share-modal" role="dialog" aria-modal="true" aria-label="导入导出">
      <header class="modal-header">
        <div>
          <span class="eyebrow">LOAD ORDER TRANSFER</span>
          <h2>分享加载顺序</h2>
        </div>
        <button type="button" class="icon-button" @click="emit('close')">×</button>
      </header>
      <div class="modal-body">
        <p class="muted-copy">
          分享码保存启用 Pack 的顺序和 Workshop 身份。导入只匹配本机已安装内容，不会自动订阅或下载。
        </p>
        <textarea
          v-model="value"
          class="share-textarea"
          rows="10"
          placeholder="点击“生成分享码”，或粘贴收到的 WMM1 分享码"
        ></textarea>
        <div class="button-row">
          <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('export')">
            生成分享码
          </button>
          <button type="button" class="secondary-button" :disabled="!value" @click="copyValue">
            复制
          </button>
          <button type="button" class="primary-button" :disabled="!!busy || !value" @click="emit('import', value)">
            导入到当前播放集
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
