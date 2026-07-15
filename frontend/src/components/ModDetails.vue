<script setup>
import { computed, ref, watch } from 'vue'

import { renderWorkshopBbcode } from '../workshopBbcode'

const props = defineProps({
  mod: { type: Object, default: null },
  preview: { type: String, default: '' },
  aiEnabled: { type: Boolean, default: false },
  generateUserData: { type: Function, default: null },
})

const emit = defineEmits(['save-user-data', 'open-folder', 'open-workshop-folder', 'open-workshop'])
const alias = ref('')
const notes = ref('')
const aiGenerating = ref(false)
const renderedDescription = computed(() => renderWorkshopBbcode(props.mod?.description || ''))

watch(
  () => props.mod,
  mod => {
    alias.value = mod?.alias || ''
    notes.value = mod?.notes || ''
  },
  { immediate: true },
)

const sourceLabels = {
  workshop: 'Steam Workshop',
  data: '游戏 Data',
}

const formatDate = value => {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

const formatAuthor = mod => {
  if (mod.author) return mod.author
  if (mod.creator_id) return '作者昵称暂不可用'
  if (mod.workshop_id) return '未获取（后台刷新工坊信息）'
  return '未知'
}

const formatSources = mod => (mod.sources?.length ? mod.sources : [mod.source])
  .map(source => sourceLabels[source] || source)
  .join(' + ')

const generateWithAi = async () => {
  if (!props.mod || !props.generateUserData || !props.aiEnabled || aiGenerating.value) return
  const requestedId = props.mod.id
  aiGenerating.value = true
  try {
    const updated = await props.generateUserData(requestedId)
    if (props.mod?.id === requestedId && updated) {
      alias.value = updated.alias || ''
      notes.value = updated.notes || ''
    }
  } catch {
    // The shared store toast contains the user-facing error.
  } finally {
    aiGenerating.value = false
  }
}
</script>

<template>
  <aside class="details-panel" data-testid="mod-details">
    <template v-if="mod">
      <div class="details-visual">
        <img v-if="preview" :src="preview" :alt="mod.effective_name" />
        <div v-else class="details-placeholder">
          <span>{{ mod.effective_name.slice(0, 1).toUpperCase() }}</span>
        </div>
        <div class="details-gradient"></div>
        <div class="details-title">
          <span class="eyebrow">{{ formatSources(mod) }}</span>
          <h1>{{ mod.effective_name }}</h1>
          <p
            class="details-source-name"
            :class="{ 'has-original-name': mod.alias && mod.display_name }"
            :title="mod.alias && mod.display_name
              ? `${mod.pack_name} · 原名：${mod.display_name}`
              : mod.pack_name"
            data-testid="mod-source-name"
          >
            <span>{{ mod.pack_name }}</span>
            <span v-if="mod.alias && mod.display_name" class="original-mod-name">
              · 原名：{{ mod.display_name }}
            </span>
          </p>
          <dl class="details-meta" aria-label="基本信息">
            <div v-if="mod.workshop_id">
              <dt>Workshop ID</dt>
              <dd :title="mod.workshop_id">{{ mod.workshop_id }}</dd>
            </div>
            <div>
              <dt>作者</dt>
              <dd :title="mod.creator_id ? `${formatAuthor(mod)} · Steam ID ${mod.creator_id}` : formatAuthor(mod)">
                {{ formatAuthor(mod) }}
              </dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{{ formatDate(mod.created_at) }}</dd>
            </div>
            <div>
              <dt>更新时间</dt>
              <dd>{{ formatDate(mod.updated_at) }}</dd>
            </div>
          </dl>
        </div>
      </div>

      <div class="details-scroll">
        <section class="detail-section">
          <h3>本地位置</h3>
          <p class="path-value" :title="mod.path">{{ mod.path }}</p>
          <div class="button-row">
            <button type="button" class="secondary-button" @click="emit('open-folder', mod.id)">
              打开目录
            </button>
            <button
              v-if="mod.cross_source_duplicate && mod.workshop_id"
              type="button"
              class="secondary-button"
              @click="emit('open-workshop-folder', mod.id)"
            >
              打开工坊目录
            </button>
            <button
              v-if="mod.workshop_id"
              type="button"
              class="secondary-button"
              @click="emit('open-workshop', mod.id)"
            >
              Workshop 页面
            </button>
          </div>
        </section>

        <section v-if="mod.description" class="detail-section">
          <h3>简介</h3>
          <div
            class="description-text workshop-bbcode"
            data-testid="workshop-description"
            v-html="renderedDescription"
          ></div>
        </section>

        <section class="detail-section">
          <h3>我的标记</h3>
          <label class="field-label">
            <span class="field-label-heading">
              <span>显示别名</span>
              <button
                type="button"
                class="ai-generate-button"
                :disabled="!aiEnabled || aiGenerating"
                :title="aiEnabled ? '按战锤术语库生成当前语言标题并总结原简介' : '请先在设置中启用并配置 AI'"
                data-testid="ai-generate-user-data"
                @click.prevent="generateWithAi"
              >
                <span v-if="aiGenerating" class="spinner"></span>
                {{ aiGenerating ? '生成中' : 'AI 生成' }}
              </button>
            </span>
            <input v-model="alias" type="text" maxlength="120" placeholder="留空时使用原名称" />
          </label>
          <label class="field-label">
            <span>备注</span>
            <textarea v-model="notes" rows="4" maxlength="2000" placeholder="记录用途、版本或个人说明"></textarea>
          </label>
          <button
            type="button"
            class="primary-button compact"
            @click="emit('save-user-data', mod.id, alias, notes)"
          >
            保存标记
          </button>
        </section>
      </div>
    </template>

    <div v-else class="details-empty">
      <span class="crest">W</span>
      <h2>选择一个 MOD</h2>
      <p>这里会显示 Pack 名称、来源、路径和 Workshop 信息。</p>
    </div>
  </aside>
</template>
