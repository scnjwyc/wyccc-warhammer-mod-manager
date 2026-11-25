<script setup>
import { computed } from 'vue'
import { currentLocale, t } from '../languages'

const props = defineProps({
  open: Boolean,
  pending: Boolean,
  report: { type: Object, default: null },
  error: { type: String, default: '' },
})
const emit = defineEmits(['close'])
const close = () => { if (!props.pending) emit('close') }
const counts = computed(() => {
  const units = props.report?.units || []
  const patched = units.filter(unit => !unit.skipped).length
  return { patched, skipped: units.length - patched, partial: units.filter(unit => !unit.skipped && unit.issues.length).length }
})
const number = computed(() => new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 3 }))
const format = value => Array.isArray(value) ? value.map(format).join(' + ') : number.value.format(value)
const transition = ([before, after]) => `${format(before)} → ${format(after)}`
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="close">
    <section class="modal-card sfo-patch-modal" role="dialog" aria-modal="true"
      :aria-label="t('sfoPatch.title')" data-testid="sfo-patch-modal">
      <header class="modal-header">
        <h2>{{ t('sfoPatch.title') }}</h2>
        <button class="icon-button" :disabled="pending" :aria-label="t('common.close')" @click="close">×</button>
      </header>
      <div class="modal-body sfo-patch-body" aria-live="polite">
        <p v-if="pending" role="status">{{ t('sfoPatch.working') }}</p>
        <p v-if="error" role="alert">{{ error }}</p>
        <template v-if="report">
          <template v-if="report.path">
            <strong>{{ report.alias }}</strong>
            <p class="patch-path">{{ report.path }}</p>
            <p>{{ t('sfoPatch.enable') }}</p>
          </template>
          <p v-else role="alert">{{ t('sfoPatch.noCompatibleUnits') }}</p>
          <p>{{ t('sfoPatch.skillScope') }}</p>
          <p v-if="report.units.length">{{ t('sfoPatch.summary', counts) }}</p>
          <details v-for="unit in report.units" :key="unit.unit" class="patch-unit" :open="unit.issues.length > 0">
            <summary>{{ unit.unit }}</summary>
            <p v-for="issue in unit.issues" :key="issue" class="patch-issue">
              {{ t(`sfoPatch.${issue}`, { name: unit.detail || '' }) }}
            </p>
            <p v-if="unit.reference">{{ t('sfoPatch.reference', { name: unit.reference }) }}</p>
            <p v-else-if="unit.health_factor || unit.melee_factor">
              {{ t('sfoPatch.fallback') }}
              <span v-if="unit.health_factor"> · {{ t('sfoPatch.hp') }} ×{{ format(unit.health_factor) }}</span>
              <span v-if="unit.melee_factor"> · {{ t('sfoPatch.melee') }} ×{{ format(unit.melee_factor) }}</span>
            </p>
            <template v-for="(values, stat) in unit.stats" :key="stat">
              <p v-if="stat === 'engine_hp'">
                {{ t('sfoPatch.engine_hp') }} · {{ values.map(transition).join(' / ') }}
              </p>
              <p v-else>{{ t(`sfoPatch.${stat}`) }} · {{ transition(values) }}</p>
            </template>
            <p v-for="projectile in unit.projectiles" :key="projectile.key">
              <strong>{{ projectile.key }}</strong><br>
              {{ t('encyclopedia.missileStrength') }} · {{ transition(projectile.direct) }}
              <span v-if="projectile.explosion">
                <br>{{ t('encyclopedia.explosionDamage') }} · {{ transition(projectile.explosion) }}
              </span>
            </p>
          </details>
          <details v-if="report.skills?.length" class="patch-unit">
            <summary>{{ t('sfoPatch.skillDamage') }} ×1.30</summary>
            <details v-for="skill in report.skills" :key="skill.key" :open="skill.missing.length > 0" class="patch-unit">
              <summary>{{ skill.key }}</summary>
              <p v-for="record in skill.damage" :key="`${record.table}/${record.key}`">
                <strong>{{ record.key }}</strong><br>
                <span v-for="(values, field) in record.stats" :key="field">
                  {{ field }} · {{ transition(values) }}<br>
                </span>
              </p>
              <p v-if="skill.missing.length" class="patch-issue">
                {{ t('sfoPatch.missingPayload', { name: skill.missing.join(', ') }) }}
              </p>
            </details>
          </details>
        </template>
      </div>
      <footer class="modal-footer sfo-patch-footer">
        <strong class="danger-text patch-compatibility-notice">{{ t('sfoPatch.compatibilityNotice') }}</strong>
        <button class="secondary-button" :disabled="pending" @click="close">{{ t('common.close') }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.sfo-patch-modal { width: min(740px, 94vw); }
.sfo-patch-body { display: grid; gap: 10px; overflow-wrap: anywhere; }
.sfo-patch-body p { margin: 0; line-height: 1.5; }
.patch-path { user-select: text; }
.patch-unit { border-top: 1px solid #bda87455; padding-top: 8px; }
.patch-unit summary { cursor: pointer; }
.patch-unit p { margin-top: 6px; }
.patch-issue { color: var(--warning-color, #cf9861); }
.sfo-patch-footer { flex-basis: auto; min-height: 62px; }
.sfo-patch-footer .secondary-button { flex-shrink: 0; }
.patch-compatibility-notice { margin: 10px auto 10px 0; font-weight: 700; line-height: 1.4; }
</style>
