<script setup>
import { computed, ref } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  session: { type: Object, default: () => ({}) },
  diagnosis: { type: Object, default: () => ({}) },
  history: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  gameRunning: { type: Boolean, default: false },
  enabledCount: { type: Number, default: 0 },
})
const emit = defineEmits(['close', 'refresh', 'start', 'confirm-trial', 'cancel', 'apply', 'restore'])
const mode = ref('bisect')
const copied = ref(false)
const confirming = computed(() => ['confirm_menu', 'confirm_exit'].includes(props.session.phase))
const modLabel = id => props.session.mods?.[id]?.name || id
const close = () => { if (!props.session.running && !props.busy) emit('close') }
const copyReport = async () => {
  try { await navigator.clipboard.writeText(props.diagnosis.report || ''); copied.value = true } catch { copied.value = false }
}
const confirmTrial = verdict => emit('confirm-trial', {
  id: props.session.id, round: props.session.round_number, verdict,
})
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="close">
    <section class="modal-card diagnostics-modal" role="dialog" aria-modal="true"
      :aria-label="t('diagnostics.title')" data-testid="diagnostics-modal">
      <header class="modal-header">
        <h2>{{ t('diagnostics.title') }}</h2>
        <button class="icon-button" :disabled="session.running || busy" :aria-label="t('common.close')" @click="close">×</button>
      </header>
      <div class="modal-body diagnostics-body">
        <p>{{ t('diagnostics.intro') }}</p>
        <p class="diagnostics-muted">{{ t('diagnostics.scope') }}</p>
        <div v-if="!session.running" class="diagnostics-controls">
          <label><input v-model="mode" type="radio" value="bisect" :disabled="busy" /> {{ t('diagnostics.bisect') }}</label>
          <label><input v-model="mode" type="radio" value="maxload" :disabled="busy" /> {{ t('diagnostics.maxload') }}</label>
          <button class="primary-button" data-testid="diagnostics-start"
            :disabled="busy || gameRunning || !enabledCount" @click="emit('start', mode)">
            {{ t('diagnostics.start') }} ({{ enabledCount }})
          </button>
        </div>
        <section v-if="session.status && session.status !== 'idle'" class="diagnostics-panel" aria-live="polite">
          <strong>{{ t(`diagnostics.${session.status}`) }}</strong>
          <p>{{ t('diagnostics.progress', { count: session.rounds?.length || 0 }) }}</p>
          <p v-if="session.running">{{ t(`diagnostics.${session.phase || 'starting'}`) }}</p>
          <p v-if="session.movies && Object.keys(session.movies).length" class="diagnostics-muted">
            {{ t('diagnostics.autoMovie', { count: Object.keys(session.movies).length }) }}
          </p>
          <p v-if="session.detail" class="diagnostics-detail">{{ session.detail }}</p>
          <div v-if="session.running" class="diagnostics-controls">
            <button class="primary-button" data-testid="diagnostics-menu-ok"
              :disabled="busy || !confirming" @click="confirmTrial('ok')">{{ t('diagnostics.menuOk') }}</button>
            <button class="secondary-button" data-testid="diagnostics-trial-crash"
              :disabled="busy || !confirming" @click="confirmTrial('crash')">{{ t('diagnostics.crashed') }}</button>
            <button class="danger-button" :disabled="busy" data-testid="diagnostics-cancel"
              @click="emit('cancel')">{{ t('diagnostics.stop') }}</button>
          </div>
          <template v-if="session.suspect_ids?.length">
            <h3>{{ t('diagnostics.suspects') }}</h3>
            <ul><li v-for="id in session.suspect_ids" :key="id">{{ modLabel(id) }}</li></ul>
            <p class="diagnostics-muted">{{ t('diagnostics.suspectHint') }}</p>
          </template>
          <div v-if="!session.running && session.can_apply" class="diagnostics-controls">
            <span>{{ t('diagnostics.excluded', { count: session.excluded_ids?.length || 0 }) }}</span>
            <button class="primary-button" :disabled="busy || gameRunning" data-testid="diagnostics-apply"
              @click="emit('apply', session)">{{ t('diagnostics.apply') }}</button>
          </div>
        </section>
        <details class="diagnostics-panel" :open="diagnosis.crashed">
          <summary>{{ t('diagnostics.previousLaunch') }}</summary>
          <p>{{ t(`diagnostics.log.${diagnosis.status || 'no_run'}`) }}</p>
          <p>{{ t('diagnostics.logCounts', { loaded: diagnosis.loaded_count || 0, expected: diagnosis.expected_count || 0 }) }}</p>
          <ul v-if="diagnosis.pending?.length">
            <li v-for="row in diagnosis.pending" :key="row.pack_name">{{ row.name || row.pack_name }}</li>
          </ul>
          <p v-if="diagnosis.pending?.length" class="diagnostics-muted">{{ t('diagnostics.suspectHint') }}</p>
          <pre v-if="diagnosis.report" class="diagnostics-report">{{ diagnosis.report }}</pre>
          <button class="secondary-button" :disabled="!diagnosis.report" @click="copyReport">{{ copied ? t('common.done') : t('common.copy') }}</button>
        </details>
        <details v-if="history.length" class="diagnostics-panel">
          <summary>{{ t('diagnostics.history') }} ({{ history.length }})</summary>
          <article v-for="run in history" :key="run.id" class="diagnostics-history-row">
            <strong>{{ new Date(run.started_at * 1000).toLocaleString() }}</strong>
            <p>{{ t(`diagnostics.${run.status}`) }}</p>
            <p v-if="run.excluded_ids?.length">{{ run.excluded_ids.map(id => run.mods?.[id]?.name || id).join(' · ') }}</p>
            <div class="diagnostics-controls">
              <button v-if="run.can_apply" class="secondary-button" :disabled="busy || session.running || gameRunning"
                @click="emit('apply', run)">{{ t('diagnostics.apply') }}</button>
              <button class="secondary-button" :disabled="busy || session.running || gameRunning"
                @click="emit('restore', run)">{{ t('diagnostics.restore') }}</button>
            </div>
          </article>
        </details>
      </div>
      <footer class="modal-footer">
        <button class="secondary-button" :disabled="busy" @click="emit('refresh')">{{ t('common.refresh') }}</button>
        <button class="secondary-button" :disabled="busy || session.running" @click="close">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.diagnostics-modal { width: min(900px, 94vw); }
.diagnostics-body { display: grid; gap: 14px; overflow-wrap: anywhere; }
.diagnostics-body p { margin: 0; line-height: 1.6; }
.diagnostics-muted { opacity: .75; font-size: 13px; }
.diagnostics-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.diagnostics-controls label { display: flex; align-items: center; gap: 6px; }
.diagnostics-panel { border: 1px solid #bda87455; border-radius: 8px; padding: 14px; }
.diagnostics-panel > * + * { margin-top: 12px; }
.diagnostics-panel ul { max-height: 160px; overflow: auto; padding-left: 22px; }
.diagnostics-panel h3 { font-size: 15px; }
.diagnostics-panel summary { cursor: pointer; font-weight: 600; }
.diagnostics-report { white-space: pre-wrap; max-height: 180px; overflow: auto; font-size: 12px; }
.diagnostics-history-row { border-top: 1px solid #bda87433; padding-top: 12px; }
</style>
