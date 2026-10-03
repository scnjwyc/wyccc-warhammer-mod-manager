<script setup>
import { computed } from 'vue'
import { currentLocale, localizedPlaysetName, t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  records: { type: Array, default: () => [] },
  selected: { type: Object, default: null },
  busy: { type: String, default: '' },
  running: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'select', 'compare', 'load', 'refresh'])
const missingCount = computed(() => props.selected?.mods?.filter(mod => mod.missing).length || 0)
const formatTime = value => new Date(value * 1000).toLocaleString(currentLocale())
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card launch-history-modal" role="dialog" aria-modal="true" :aria-label="t('launchHistory.title')">
      <header class="modal-header">
        <div><h2>{{ t('launchHistory.title') }}</h2><small>{{ t('launchHistory.intro') }}</small></div>
        <button type="button" class="icon-button" :aria-label="t('common.close')" @click="emit('close')">×</button>
      </header>
      <div class="launch-history-layout">
        <div class="launch-history-records">
          <button v-for="record in records" :key="record.id" type="button"
            class="launch-history-record" :class="{ selected: selected?.id === record.id }"
            :disabled="!!busy" :data-record-id="record.id" data-testid="launch-history-record"
            @click="emit('select', record.id)">
            <strong>{{ formatTime(record.started_at) }}</strong>
            <span>{{ t('launchHistory.modCount', { count: record.mod_count }) }}</span>
            <small v-if="record.playset_name">{{ localizedPlaysetName({ name: record.playset_name }) }}</small>
            <small v-if="record.save_name">{{ record.save_name }}</small>
          </button>
          <p v-if="!records.length" class="launch-history-empty" data-testid="no-launch-record">{{ t('launchHistory.none') }}</p>
        </div>
        <div class="launch-history-detail">
          <template v-if="selected">
            <h3>{{ formatTime(selected.started_at) }}</h3>
            <p v-if="missingCount" class="launch-history-missing">{{ t('launchHistory.missing', { count: missingCount }) }}</p>
            <ol class="launch-history-mods" data-testid="launch-history-mods">
              <li v-for="(mod, index) in selected.mods" :key="`${mod.id || mod.pack_name}:${index}`">
                <strong>{{ mod.effective_name || mod.display_name || t('launchHistory.unknownMod') }}</strong>
                <small v-if="mod.missing">{{ t('launchHistory.notInstalled') }}</small>
              </li>
            </ol>
            <p v-if="!selected.mods.length" class="launch-history-empty">{{ t('launchHistory.noMods') }}</p>
          </template>
          <p v-else-if="records.length" class="launch-history-empty">{{ t('launchHistory.select') }}</p>
        </div>
      </div>
      <footer class="modal-footer">
        <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('refresh')">{{ t('common.refresh') }}</button>
        <button type="button" class="secondary-button" :disabled="!selected || !!busy" data-testid="launch-history-compare"
          @click="emit('compare', selected.id)">{{ t('launchHistory.compare') }}</button>
        <button type="button" class="primary-button" :disabled="!selected || !!busy || running" data-testid="launch-history-load"
          @click="emit('load', selected.id)">{{ t('launchHistory.load') }}</button>
        <button type="button" class="secondary-button" @click="emit('close')">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>
