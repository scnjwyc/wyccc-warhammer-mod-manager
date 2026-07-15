<script setup>
import { computed } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  mode: { type: String, default: 'update' },
  info: { type: Object, default: null },
  changelog: { type: Array, default: () => [] },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'download', 'install', 'ignore'])
const isReady = computed(() => props.info?.status === 'ready')

const formatSize = value => {
  const bytes = Number(value || 0)
  if (!bytes) return '未知大小'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

const typeLabel = type => ({
  feature: '新增',
  fix: '修复',
  optimize: '优化',
  breaking: '注意',
  change: '变更',
}[type] || '变更')
</script>

<template>
  <div v-if="open" class="modal-backdrop update-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card update-modal" role="dialog" aria-modal="true" :aria-label="mode === 'changelog' ? '更新日志' : '软件更新'">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ mode === 'changelog' ? 'CHANGELOG' : 'SOFTWARE UPDATE' }}</span>
          <h2>{{ mode === 'changelog' ? '更新日志' : `发现新版本 v${info?.version || ''}` }}</h2>
        </div>
        <button type="button" class="icon-button" :disabled="!!busy" @click="emit('close')">×</button>
      </header>

      <div v-if="mode === 'update'" class="modal-body update-body">
        <div class="update-summary">
          <div>
            <span>当前版本</span>
            <strong>v{{ info?.current_version }}</strong>
          </div>
          <span class="update-arrow">→</span>
          <div>
            <span>可用版本</span>
            <strong>v{{ info?.version }}</strong>
          </div>
          <div class="update-meta">
            <span>{{ formatSize(info?.size) }}</span>
            <span v-if="info?.published_at">{{ info.published_at }}</span>
            <span :class="isReady ? 'verified' : ''">{{ isReady ? 'SHA-256 已校验' : '等待下载校验' }}</span>
          </div>
        </div>

        <div class="changelog-list compact-log">
          <section v-for="(entry, entryIndex) in info?.entries || []" :key="`${entry.title}:${entryIndex}`" class="change-entry">
            <h3>{{ entry.title }}</h3>
            <ul>
              <li v-for="(change, changeIndex) in entry.changes || []" :key="`${change.text}:${changeIndex}`">
                <span class="change-type" :class="`type-${change.type}`">{{ typeLabel(change.type) }}</span>
                <span>{{ change.text }}</span>
              </li>
            </ul>
          </section>
          <p v-if="!info?.entries?.length" class="empty-changelog">此版本未提供更新说明。</p>
        </div>
      </div>

      <div v-else class="modal-body changelog-body">
        <div class="changelog-list">
          <article v-for="release in changelog" :key="release.version" class="release-entry">
            <header>
              <strong>v{{ release.version }}</strong>
              <time v-if="release.date">{{ release.date }}</time>
            </header>
            <section v-for="(entry, entryIndex) in release.entries || []" :key="`${release.version}:${entryIndex}`" class="change-entry">
              <h3>{{ entry.title }}</h3>
              <ul>
                <li v-for="(change, changeIndex) in entry.changes || []" :key="`${change.text}:${changeIndex}`">
                  <span class="change-type" :class="`type-${change.type}`">{{ typeLabel(change.type) }}</span>
                  <span>{{ change.text }}</span>
                </li>
              </ul>
            </section>
          </article>
          <p v-if="!changelog.length" class="empty-changelog">暂无更新日志。</p>
        </div>
      </div>

      <footer class="modal-footer update-footer">
        <template v-if="mode === 'update'">
          <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('ignore')">忽略此版本</button>
          <span class="footer-spacer"></span>
          <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">稍后提醒</button>
          <button v-if="!isReady" type="button" class="primary-button" :disabled="!!busy" @click="emit('download')">
            {{ busy || '下载更新' }}
          </button>
          <button v-else type="button" class="primary-button" :disabled="!!busy" @click="emit('install')">
            {{ busy || '安装并重启' }}
          </button>
        </template>
        <button v-else type="button" class="primary-button" :disabled="!!busy" @click="emit('close')">关闭</button>
      </footer>
    </section>
  </div>
</template>
