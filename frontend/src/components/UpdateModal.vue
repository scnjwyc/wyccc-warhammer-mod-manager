<script setup>
import { computed } from 'vue'
import { t } from '../languages'

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
  if (!bytes) return t('update.unknownSize')
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

const typeLabel = type => ({
  feature: t('update.typeFeature'),
  fix: t('update.typeFix'),
  optimize: t('update.typeOptimize'),
  improvement: t('update.typeOptimize'),
  breaking: t('update.typeBreaking'),
  change: t('update.typeChange'),
}[type] || t('update.typeChange'))
</script>

<template>
  <div v-if="open" class="modal-backdrop update-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card update-modal" role="dialog" aria-modal="true" :aria-label="mode === 'changelog' ? t('update.changelog') : t('update.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ mode === 'changelog' ? t('update.changelog') : t('update.eyebrow') }}</span>
          <h2>{{ mode === 'changelog' ? t('update.changelog') : t('update.found', { version: info?.version || '' }) }}</h2>
        </div>
        <button type="button" class="icon-button" :disabled="!!busy" @click="emit('close')">×</button>
      </header>

      <div v-if="mode === 'update'" class="modal-body update-body">
        <div class="update-summary">
          <div>
            <span>{{ t('update.currentVersion') }}</span>
            <strong>v{{ info?.current_version }}</strong>
          </div>
          <span class="update-arrow">→</span>
          <div>
            <span>{{ t('update.availableVersion') }}</span>
            <strong>v{{ info?.version }}</strong>
          </div>
          <div class="update-meta">
            <span>{{ formatSize(info?.size) }}</span>
            <span v-if="info?.published_at">{{ info.published_at }}</span>
            <span :class="isReady ? 'verified' : ''">{{ isReady ? t('update.verified') : t('update.waiting') }}</span>
          </div>
        </div>

        <div class="changelog-list compact-log">
          <ul v-if="info?.entries?.length" class="change-list">
            <template v-for="(entry, entryIndex) in info.entries" :key="`${entry.title}:${entryIndex}`">
              <li v-for="(change, changeIndex) in entry.changes || []" :key="`${change.text}:${changeIndex}`">
                <span class="change-type" :class="`type-${change.type}`">{{ typeLabel(change.type) }}</span>
                <span>{{ change.text }}</span>
              </li>
            </template>
          </ul>
          <p v-else class="empty-changelog">{{ t('update.noVersionNotes') }}</p>
        </div>
      </div>

      <div v-else class="modal-body changelog-body">
        <div class="changelog-list">
          <article v-for="release in changelog" :key="release.version" class="release-entry">
            <header>
              <strong>v{{ release.version }}</strong>
              <time v-if="release.date">{{ release.date }}</time>
            </header>
            <ul class="change-list">
              <template v-for="(entry, entryIndex) in release.entries || []" :key="`${release.version}:${entryIndex}`">
                <li v-for="(change, changeIndex) in entry.changes || []" :key="`${change.text}:${changeIndex}`">
                  <span class="change-type" :class="`type-${change.type}`">{{ typeLabel(change.type) }}</span>
                  <span>{{ change.text }}</span>
                </li>
              </template>
            </ul>
          </article>
          <p v-if="!changelog.length" class="empty-changelog">{{ t('update.noChangelog') }}</p>
        </div>
      </div>

      <footer class="modal-footer update-footer">
        <template v-if="mode === 'update'">
          <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('ignore')">{{ t('update.ignoreVersion') }}</button>
          <span class="footer-spacer"></span>
          <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">{{ t('update.remindLater') }}</button>
          <button v-if="!isReady" type="button" class="primary-button" :disabled="!!busy" @click="emit('download')">
            {{ busy || t('update.download') }}
          </button>
          <button v-else type="button" class="primary-button" :disabled="!!busy" @click="emit('install')">
            {{ busy || t('update.install') }}
          </button>
        </template>
        <button v-else type="button" class="primary-button" :disabled="!!busy" @click="emit('close')">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>
