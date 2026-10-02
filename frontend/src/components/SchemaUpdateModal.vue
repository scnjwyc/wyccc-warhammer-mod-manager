<script setup>
import { localizeBackendMessage, t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  pending: { type: Boolean, default: false },
  report: { type: Object, default: null },
  error: { type: String, default: '' },
})
const emit = defineEmits(['close'])
const close = () => { if (!props.pending) emit('close') }
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="close">
    <section class="modal-card schema-update-modal" role="dialog" aria-modal="true"
      :aria-label="t('schemaUpdate.title')" data-testid="schema-update-modal">
      <header class="modal-header">
        <h2>{{ t('schemaUpdate.title') }}</h2>
        <button class="icon-button" :disabled="pending" :aria-label="t('common.close')" @click="close">×</button>
      </header>
      <div class="modal-body schema-update-body" aria-live="polite">
        <p>{{ t('schemaUpdate.intro') }}</p>
        <p v-if="pending" role="status">{{ t('schemaUpdate.working') }}</p>
        <p v-if="error" role="alert">{{ localizeBackendMessage(error) }}</p>
        <template v-if="report">
          <strong>{{ t('schemaUpdate.summary', { updated: report.updated_count, unchanged: report.unchanged_count,
            partial: report.partial_count, failed: report.failed_count }) }}</strong>
          <p v-if="report.schema?.cached" role="alert">{{ t('schemaUpdate.cached') }}</p>
          <article v-for="row in report.results" :key="row.mod_id" class="schema-result" :data-status="row.status">
            <h3>{{ row.name }} · {{ t(`schemaUpdate.${row.status}`) }}</h3>
            <p v-if="row.error" role="alert">{{ localizeBackendMessage(row.error) }}</p>
            <p v-if="row.backup_path" class="schema-backup">{{ t('schemaUpdate.backup', { path: row.backup_path }) }}</p>
            <details v-if="row.tables?.length || row.skipped?.length"
              :open="row.status === 'partial' || row.tables?.some(table => table.reset_values)">
              <summary>{{ row.path }}</summary>
              <div v-for="table in row.tables" :key="table.path" class="schema-table">
                <p>{{ t('schemaUpdate.table', { path: table.path, from: table.from_version,
                  to: table.to_version, rows: table.rows }) }}</p>
                <p v-if="table.reset_values">{{ t('schemaUpdate.reset', { count: table.reset_values }) }}</p>
              </div>
              <p v-for="table in row.skipped" :key="table.path">{{ table.path }}: {{ localizeBackendMessage(table.reason) }}</p>
            </details>
          </article>
        </template>
      </div>
      <footer class="modal-footer">
        <button class="secondary-button" :disabled="pending" @click="close">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.schema-update-modal { width: min(850px, 94vw); }
.schema-update-body { display: grid; gap: 14px; overflow-wrap: anywhere; }
.schema-update-body p { margin: 0; line-height: 1.6; }
.schema-result { border-top: 1px solid #bda87455; padding-top: 12px; }
.schema-result h3 { margin: 0 0 8px; font-size: 15px; }
.schema-result[data-status="failed"], .schema-result[data-status="partial"] { color: var(--warning-color, #cf9861); }
.schema-backup { user-select: text; font-size: 12px; opacity: .8; }
.schema-table { margin-top: 8px; }
.schema-result details { margin-top: 8px; }
.schema-result summary { cursor: pointer; }
</style>
