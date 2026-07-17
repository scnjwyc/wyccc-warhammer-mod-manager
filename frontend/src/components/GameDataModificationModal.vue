<script setup>
import { computed, reactive, watch } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  settings: { type: Object, default: () => ({}) },
  busy: { type: String, default: '' },
  unitSizeSubscribed: { type: Boolean, default: true },
  friendlyFireSubscribed: { type: Boolean, default: true },
  unitSizeModName: { type: String, default: 'Dynamic Unit Size' },
  friendlyFireModName: { type: String, default: 'Dynamic No Friendly Fire' },
})

const emit = defineEmits(['close', 'save'])
const UNIT_MODEL_MULTIPLIER_MIN = 1
const UNIT_MODEL_MULTIPLIER_MAX = 5
const UNIT_MODEL_MULTIPLIER_STEPS = [1, 2, 3, 4, 5]
const draft = reactive({
  unit_model_multiplier: 1,
  scale_lord_hero_health: false,
  disable_unit_friendly_fire: false,
  disable_spell_friendly_fire: false,
})

const normalizeMultiplier = value => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 1
  const clamped = Math.max(
    UNIT_MODEL_MULTIPLIER_MIN,
    Math.min(UNIT_MODEL_MULTIPLIER_MAX, numeric),
  )
  return Math.round(clamped)
}

const unitSizeAvailable = computed(() => props.unitSizeSubscribed)
const friendlyFireAvailable = computed(() => props.friendlyFireSubscribed)
const requirementMessage = modName => t('gameData.requiredModNotSubscribed', { mod: modName })

const resetDraft = () => {
  draft.unit_model_multiplier = normalizeMultiplier(props.settings.unit_model_multiplier ?? 1)
  draft.scale_lord_hero_health = !!props.settings.scale_lord_hero_health
  draft.disable_unit_friendly_fire = !!props.settings.disable_unit_friendly_fire
  draft.disable_spell_friendly_fire = !!props.settings.disable_spell_friendly_fire
}

watch(
  () => props.open,
  open => {
    if (open) resetDraft()
  },
  { immediate: true },
)

watch(
  () => props.settings,
  () => {
    if (props.open) resetDraft()
  },
  { deep: true },
)

const currentSettings = () => ({
  unit_model_multiplier: normalizeMultiplier(draft.unit_model_multiplier),
  scale_lord_hero_health: !!draft.scale_lord_hero_health,
  disable_unit_friendly_fire: !!draft.disable_unit_friendly_fire,
  disable_spell_friendly_fire: !!draft.disable_spell_friendly_fire,
})

const submit = () => {
  if (!unitSizeAvailable.value && !friendlyFireAvailable.value) return
  emit('save', currentSettings())
}

</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <form class="modal-card game-data-modal" role="dialog" aria-modal="true" :aria-label="t('gameData.aria')" @submit.prevent="submit">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('gameData.eyebrow') }}</span>
          <h2>{{ t('gameData.title') }}</h2>
        </div>
        <button type="button" class="icon-button" :aria-label="t('common.close')" @click="emit('close')">×</button>
      </header>

      <div class="modal-body game-data-body">
        <p class="game-data-intro">{{ t('gameData.intro') }}</p>

        <section class="game-data-card multiplier-card" :class="{ unavailable: !unitSizeAvailable }">
          <div class="game-data-card-copy">
            <strong>{{ t('gameData.unitMultiplier') }}</strong>
            <small>{{ t('gameData.unitMultiplierHelp') }}</small>
            <p v-if="!unitSizeAvailable" class="game-data-requirement" data-testid="unit-size-requirement">
              {{ requirementMessage(unitSizeModName) }}
            </p>
          </div>
          <div class="unit-scale-control">
            <div class="unit-scale-slider-row">
              <input
                v-model.number="draft.unit_model_multiplier"
                type="range"
                :min="UNIT_MODEL_MULTIPLIER_MIN"
                :max="UNIT_MODEL_MULTIPLIER_MAX"
                step="1"
                :disabled="!!busy || !unitSizeAvailable"
                :aria-label="t('gameData.unitMultiplier')"
                data-testid="unit-model-multiplier"
              />
              <output class="unit-scale-value" data-testid="unit-scale-value">
                {{ normalizeMultiplier(draft.unit_model_multiplier) }}×
              </output>
            </div>
            <div class="unit-scale-ticks" data-testid="unit-scale-ticks" aria-hidden="true">
              <span v-for="step in UNIT_MODEL_MULTIPLIER_STEPS" :key="step">{{ step }}</span>
            </div>
          </div>
          <label class="switch-row character-health-toggle">
            <input
              v-model="draft.scale_lord_hero_health"
              type="checkbox"
              :disabled="!!busy || !unitSizeAvailable"
              data-testid="scale-lord-hero-health"
            />
            <span>
              <strong>{{ t('gameData.scaleLordHeroHealth') }}</strong>
              <small>{{ t('gameData.scaleLordHeroHealthHelp') }}</small>
            </span>
          </label>
        </section>

        <section class="game-data-card friendly-fire-card" :class="{ unavailable: !friendlyFireAvailable }">
          <p v-if="!friendlyFireAvailable" class="game-data-requirement" data-testid="friendly-fire-requirement">
            {{ requirementMessage(friendlyFireModName) }}
          </p>
          <label class="switch-row">
            <input v-model="draft.disable_unit_friendly_fire" type="checkbox" :disabled="!!busy || !friendlyFireAvailable" data-testid="disable-unit-friendly-fire" />
            <span>
              <strong>{{ t('gameData.disableUnitFriendlyFire') }}</strong>
              <small>{{ t('gameData.disableUnitFriendlyFireHelp') }}</small>
            </span>
          </label>
          <label class="switch-row">
            <input v-model="draft.disable_spell_friendly_fire" type="checkbox" :disabled="!!busy || !friendlyFireAvailable" data-testid="disable-spell-friendly-fire" />
            <span>
              <strong>{{ t('gameData.disableSpellFriendlyFire') }}</strong>
              <small>{{ t('gameData.disableSpellFriendlyFireHelp') }}</small>
            </span>
          </label>
        </section>

        <div class="game-data-note">
          <p>{{ t('gameData.runtimeNote') }}</p>
          <p>{{ t('gameData.friendlyEffectsNote') }}</p>
        </div>
      </div>

      <footer class="modal-footer game-data-footer">
        <div class="game-data-footer-content" data-testid="game-data-footer-content">
          <div class="game-data-footer-actions" data-testid="game-data-footer-actions">
            <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">
              {{ t('common.cancel') }}
            </button>
            <button type="submit" class="primary-button" :disabled="!!busy || (!unitSizeAvailable && !friendlyFireAvailable)">
              {{ busy || t('gameData.save') }}
            </button>
          </div>
          <p class="game-data-regeneration-warning" data-testid="game-data-regeneration-warning">
            {{ t('gameData.autoGenerateOnLaunch') }}
          </p>
        </div>
      </footer>
    </form>
  </div>
</template>

<style scoped>
.game-data-modal {
  width: min(700px, 94vw);
}

.game-data-body {
  display: grid;
  gap: 15px;
  padding: 22px;
}

.game-data-intro {
  margin: 0;
  color: #aa9a90;
  font-size: 12px;
  line-height: 1.7;
}

.game-data-card {
  border: 1px solid #46332d;
  border-radius: 6px;
  background: rgba(13, 10, 10, 0.62);
}

.game-data-card.unavailable {
  border-color: #3b302d;
  opacity: 0.72;
}

.game-data-requirement {
  margin: 3px 0 0;
  color: #d69b65;
  font-size: 11px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.multiplier-card {
  display: grid;
  gap: 14px;
  padding: 17px 18px;
}

.game-data-card-copy {
  display: grid;
  gap: 5px;
}

.game-data-card-copy strong,
.character-health-toggle strong,
.friendly-fire-card :deep(.switch-row strong) {
  color: #ead9ca;
  font-size: 13px;
}

.game-data-card-copy small,
.character-health-toggle small,
.friendly-fire-card :deep(.switch-row small) {
  color: #8d7f77;
  font-size: 11px;
  line-height: 1.55;
}

.unit-scale-control {
  display: grid;
  gap: 3px;
}

.unit-scale-slider-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.unit-scale-slider-row input {
  min-width: 0;
  flex: 1;
  accent-color: #b87a3c;
}

.unit-scale-value {
  min-width: 52px;
  padding: 7px 9px;
  border: 1px solid #75523b;
  border-radius: 4px;
  background: #0e0b0b;
  color: #f1d29a;
  font-size: 15px;
  font-weight: 800;
  text-align: center;
}

.unit-scale-ticks {
  display: flex;
  justify-content: space-between;
  margin-right: 66px;
  color: #75675f;
  font-size: 10px;
  text-align: center;
}

.character-health-toggle {
  min-height: 62px;
  padding-top: 12px;
  border-top: 1px solid #302522;
  border-bottom: 0;
}

.friendly-fire-card {
  overflow: hidden;
  padding: 2px 15px;
}

.friendly-fire-card > .game-data-requirement {
  margin: 11px 2px 3px;
}

.friendly-fire-card .switch-row {
  min-height: 66px;
  border-bottom: 0;
}

.friendly-fire-card .switch-row + .switch-row {
  border-top: 1px solid #302522;
}

.game-data-note {
  padding: 12px 14px;
  border-left: 3px solid #8b633b;
  border-radius: 3px;
  background: rgba(92, 58, 31, 0.16);
}

.game-data-note p {
  margin: 0;
  color: #a99686;
  font-size: 11px;
  line-height: 1.65;
}

.game-data-note p + p {
  margin-top: 5px;
}

.game-data-modal > .game-data-footer {
  flex-basis: auto;
  min-height: 92px;
  padding-top: 10px;
  padding-bottom: 10px;
}

.game-data-footer-content {
  display: grid;
  width: 100%;
  gap: 5px;
  justify-items: end;
}

.game-data-footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 9px;
}

.game-data-regeneration-warning {
  justify-self: end;
  margin: 0;
  max-width: min(520px, 100%);
  color: #d69b65;
  font-size: 11px;
  line-height: 1.45;
  text-align: left;
}

@media (max-width: 620px) {
  .unit-scale-slider-row {
    gap: 9px;
  }

  .game-data-modal > .game-data-footer {
    padding: 12px 14px;
  }

  .game-data-footer-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .game-data-footer-actions > button {
    width: 100%;
  }

  .game-data-regeneration-warning {
    justify-self: stretch;
  }
}
</style>
