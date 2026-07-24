<script setup>
import { computed, reactive, watch } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: { type: Boolean, default: false },
  settings: { type: Object, default: () => ({}) },
  busy: { type: String, default: '' },
  unitSizeSubscribed: { type: Boolean, default: true },
  friendlyFireSubscribed: { type: Boolean, default: true },
  unitCapacitySubscribed: { type: Boolean, default: true },
  unitSizeModName: { type: String, default: 'Dynamic Unit Size' },
  friendlyFireModName: { type: String, default: 'Dynamic No Friendly Fire' },
  unitCapacityModName: { type: String, default: '动态单位容量 - Dynamic Unit Cap' },
})

const emit = defineEmits(['close', 'save'])
const UNIT_MODEL_MULTIPLIER_MIN = 1
const UNIT_MODEL_MULTIPLIER_MAX = 5
const UNIT_MODEL_MULTIPLIER_STEPS = [1, 2, 3, 4, 5]
const UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MIN = 1
const UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MAX = 5
const UNIT_RECRUITMENT_CAPACITY_UNLIMITED_SLIDER_VALUE = 6
const UNLIMITED_LABEL = String.fromCharCode(0x221e)
const MULTIPLIER_LABEL = String.fromCharCode(0xd7)
const UNIT_RECRUITMENT_CAPACITY_STEPS = [1, 2, 3, 4, 5, UNLIMITED_LABEL]
const SINGLE_ENTITY_UNIT_MODE_HEALTH = 'health'
const SINGLE_ENTITY_UNIT_MODE_SCALE = 'scale'
const CATEGORY_UNIT_MODE_FULL = 'full'
const CATEGORY_UNIT_MODE_OPTIONS = Object.freeze([
  { value: 'health', labelKey: 'gameData.categoryUnitHealth' },
  { value: 'half', labelKey: 'gameData.categoryUnitHalf' },
  { value: 'full', labelKey: 'gameData.categoryUnitFull' },
])
const CATEGORY_UNIT_CONTROLS = Object.freeze([
  {
    setting: 'artillery_unit_mode',
    testId: 'artillery',
    labelKey: 'gameData.artilleryUnitMode',
    helpKey: 'gameData.artilleryUnitModeHelp',
  },
  {
    setting: 'war_machine_unit_mode',
    testId: 'war-machine',
    labelKey: 'gameData.warMachineUnitMode',
    helpKey: 'gameData.warMachineUnitModeHelp',
  },
])
const draft = reactive({
  unit_model_multiplier: 1,
  unit_recruitment_capacity_multiplier: 1,
  single_entity_unit_mode: SINGLE_ENTITY_UNIT_MODE_SCALE,
  artillery_unit_mode: CATEGORY_UNIT_MODE_FULL,
  war_machine_unit_mode: CATEGORY_UNIT_MODE_FULL,
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

const normalizeRecruitmentCapacityMultiplier = value => {
  const numeric = Number(value)
  if (numeric === 0) return 0
  if (!Number.isFinite(numeric)) return 1
  return Math.round(Math.max(
    UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MIN,
    Math.min(UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MAX, numeric),
  ))
}

const normalizeSingleEntityUnitMode = value => (
  String(value || '').trim().toLowerCase() === SINGLE_ENTITY_UNIT_MODE_HEALTH
    ? SINGLE_ENTITY_UNIT_MODE_HEALTH
    : SINGLE_ENTITY_UNIT_MODE_SCALE
)

const normalizeCategoryUnitMode = value => {
  const normalized = String(value || '').trim().toLowerCase()
  return CATEGORY_UNIT_MODE_OPTIONS.some(option => option.value === normalized)
    ? normalized
    : CATEGORY_UNIT_MODE_FULL
}

const categoryUnitModeHelpKey = value => ({
  health: 'gameData.categoryUnitHealthHelp',
  half: 'gameData.categoryUnitHalfHelp',
  full: 'gameData.categoryUnitFullHelp',
}[normalizeCategoryUnitMode(value)])

const unitSizeAvailable = computed(() => props.unitSizeSubscribed)
const friendlyFireAvailable = computed(() => props.friendlyFireSubscribed)
const unitCapacityAvailable = computed(() => props.unitCapacitySubscribed)
const requirementMessage = modName => t('gameData.requiredModNotSubscribed', { mod: modName })
const recruitmentCapacitySliderValue = computed({
  get: () => (
    normalizeRecruitmentCapacityMultiplier(draft.unit_recruitment_capacity_multiplier) === 0
      ? UNIT_RECRUITMENT_CAPACITY_UNLIMITED_SLIDER_VALUE
      : normalizeRecruitmentCapacityMultiplier(draft.unit_recruitment_capacity_multiplier)
  ),
  set: value => {
    const numeric = Number(value)
    draft.unit_recruitment_capacity_multiplier = (
      numeric >= UNIT_RECRUITMENT_CAPACITY_UNLIMITED_SLIDER_VALUE
        ? 0
        : normalizeRecruitmentCapacityMultiplier(numeric)
    )
  },
})

const resetDraft = () => {
  draft.unit_model_multiplier = normalizeMultiplier(props.settings.unit_model_multiplier ?? 1)
  draft.unit_recruitment_capacity_multiplier = normalizeRecruitmentCapacityMultiplier(
    props.settings.unit_recruitment_capacity_multiplier ?? 1,
  )
  draft.single_entity_unit_mode = normalizeSingleEntityUnitMode(props.settings.single_entity_unit_mode)
  draft.artillery_unit_mode = normalizeCategoryUnitMode(props.settings.artillery_unit_mode)
  draft.war_machine_unit_mode = normalizeCategoryUnitMode(props.settings.war_machine_unit_mode)
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
  unit_recruitment_capacity_multiplier: normalizeRecruitmentCapacityMultiplier(
    draft.unit_recruitment_capacity_multiplier,
  ),
  single_entity_unit_mode: normalizeSingleEntityUnitMode(draft.single_entity_unit_mode),
  artillery_unit_mode: normalizeCategoryUnitMode(draft.artillery_unit_mode),
  war_machine_unit_mode: normalizeCategoryUnitMode(draft.war_machine_unit_mode),
  scale_lord_hero_health: !!draft.scale_lord_hero_health,
  disable_unit_friendly_fire: !!draft.disable_unit_friendly_fire,
  disable_spell_friendly_fire: !!draft.disable_spell_friendly_fire,
})

const submit = () => {
  if (!unitSizeAvailable.value && !friendlyFireAvailable.value && !unitCapacityAvailable.value) return
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
          <div class="single-entity-mode-control">
            <div class="single-entity-mode-row">
              <strong>{{ t('gameData.singleEntityUnitMode') }}</strong>
              <div
                class="single-entity-mode-toggle"
                role="group"
                :aria-label="t('gameData.singleEntityUnitMode')"
                data-testid="single-entity-unit-mode"
              >
                <button
                  type="button"
                  class="single-entity-mode-choice"
                  :class="{ active: draft.single_entity_unit_mode === SINGLE_ENTITY_UNIT_MODE_HEALTH }"
                  :aria-pressed="draft.single_entity_unit_mode === SINGLE_ENTITY_UNIT_MODE_HEALTH"
                  :disabled="!!busy || !unitSizeAvailable"
                  data-testid="single-entity-unit-mode-health"
                  @click="draft.single_entity_unit_mode = SINGLE_ENTITY_UNIT_MODE_HEALTH"
                >
                  {{ t('gameData.singleEntityHealth') }}
                </button>
                <button
                  type="button"
                  class="single-entity-mode-choice"
                  :class="{ active: draft.single_entity_unit_mode === SINGLE_ENTITY_UNIT_MODE_SCALE }"
                  :aria-pressed="draft.single_entity_unit_mode === SINGLE_ENTITY_UNIT_MODE_SCALE"
                  :disabled="!!busy || !unitSizeAvailable"
                  data-testid="single-entity-unit-mode-scale"
                  @click="draft.single_entity_unit_mode = SINGLE_ENTITY_UNIT_MODE_SCALE"
                >
                  {{ t('gameData.singleEntityScale') }}
                </button>
              </div>
            </div>
            <small>{{ t('gameData.singleEntityUnitModeHelp') }}</small>
          </div>
          <div
            v-for="control in CATEGORY_UNIT_CONTROLS"
            :key="control.setting"
            class="single-entity-mode-control category-unit-mode-control"
          >
            <div class="single-entity-mode-row">
              <strong>{{ t(control.labelKey) }}</strong>
              <div
                class="single-entity-mode-toggle category-unit-mode-toggle"
                role="group"
                :aria-label="t(control.labelKey)"
                :data-testid="`${control.testId}-unit-mode`"
              >
                <button
                  v-for="option in CATEGORY_UNIT_MODE_OPTIONS"
                  :key="option.value"
                  type="button"
                  class="single-entity-mode-choice"
                  :class="{ active: draft[control.setting] === option.value }"
                  :aria-pressed="draft[control.setting] === option.value"
                  :disabled="!!busy || !unitSizeAvailable"
                  :data-testid="`${control.testId}-unit-mode-${option.value}`"
                  @click="draft[control.setting] = option.value"
                >
                  {{ t(option.labelKey) }}
                </button>
              </div>
            </div>
            <small>{{ t(control.helpKey) }}</small>
            <small
              class="category-unit-mode-help"
              :data-testid="`${control.testId}-unit-mode-help`"
            >
              {{ t(categoryUnitModeHelpKey(draft[control.setting])) }}
            </small>
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

        <section class="game-data-card multiplier-card unit-capacity-card" :class="{ unavailable: !unitCapacityAvailable }">
          <div class="game-data-card-copy">
            <strong>{{ t('gameData.unitRecruitmentCapacityMultiplier') }}</strong>
            <small>{{ t('gameData.unitRecruitmentCapacityMultiplierHelp') }}</small>
            <p v-if="!unitCapacityAvailable" class="game-data-requirement" data-testid="unit-capacity-requirement">
              {{ requirementMessage(unitCapacityModName) }}
            </p>
          </div>
          <div class="unit-scale-control">
            <div class="unit-scale-slider-row">
              <input
                v-model.number="recruitmentCapacitySliderValue"
                type="range"
                :min="UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MIN"
                :max="UNIT_RECRUITMENT_CAPACITY_UNLIMITED_SLIDER_VALUE"
                step="1"
                :disabled="!!busy || !unitCapacityAvailable"
                :aria-label="t('gameData.unitRecruitmentCapacityMultiplier')"
                data-testid="unit-recruitment-capacity-multiplier"
              />
              <output class="unit-scale-value" data-testid="unit-recruitment-capacity-value">
                {{ normalizeRecruitmentCapacityMultiplier(draft.unit_recruitment_capacity_multiplier) === 0 ? UNLIMITED_LABEL : `${normalizeRecruitmentCapacityMultiplier(draft.unit_recruitment_capacity_multiplier)}${MULTIPLIER_LABEL}` }}
              </output>
            </div>
            <div class="unit-scale-ticks" data-testid="unit-recruitment-capacity-ticks" aria-hidden="true">
              <span v-for="step in UNIT_RECRUITMENT_CAPACITY_STEPS" :key="step">{{ step === UNLIMITED_LABEL ? step : `${step}${MULTIPLIER_LABEL}` }}</span>
            </div>
          </div>
        </section>

        <div class="game-data-note">
          <p>{{ t('gameData.runtimeNote') }}</p>
          <p>{{ t('gameData.friendlyEffectsNote') }}</p>
        </div>
      </div>

      <footer class="modal-footer game-data-footer">
        <div class="game-data-footer-content" data-testid="game-data-footer-content">
          <p class="game-data-regeneration-warning" data-testid="game-data-regeneration-warning">
            {{ t('gameData.autoGenerateOnLaunch') }}
          </p>
          <div class="game-data-footer-actions" data-testid="game-data-footer-actions">
            <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">
              {{ t('common.cancel') }}
            </button>
            <button type="submit" class="primary-button" :disabled="!!busy || (!unitSizeAvailable && !friendlyFireAvailable && !unitCapacityAvailable)">
              {{ busy || t('gameData.save') }}
            </button>
          </div>
        </div>
      </footer>
    </form>
  </div>
</template>

<style scoped>
.game-data-modal {
  width: min(760px, 94vw);
}

.game-data-modal .eyebrow {
  font-size: 13px;
}

.game-data-modal .modal-header h2 {
  font-size: 22px;
}

.game-data-modal .modal-footer button {
  font-size: 14px;
}

.game-data-body {
  display: grid;
  grid-auto-rows: max-content;
  align-content: start;
  gap: 15px;
  padding: 22px;
}

.game-data-intro {
  margin: 0;
  color: #aa9a90;
  font-size: 14px;
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
  font-size: 13px;
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
  font-size: 16px;
}

.game-data-card-copy small,
.character-health-toggle small,
.friendly-fire-card :deep(.switch-row small) {
  color: #8d7f77;
  font-size: 13px;
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
  font-size: 18px;
  font-weight: 800;
  text-align: center;
}

.unit-scale-ticks {
  display: flex;
  justify-content: space-between;
  margin-right: 66px;
  color: #75675f;
  font-size: 12px;
  text-align: center;
}

.single-entity-mode-control {
  display: grid;
  gap: 5px;
  padding-top: 12px;
  border-top: 1px solid #302522;
}

.single-entity-mode-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.single-entity-mode-row strong {
  color: #ead9ca;
  font-size: 16px;
}

.single-entity-mode-toggle {
  display: grid;
  width: min(230px, 52%);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid #594238;
  border-radius: 5px;
  background: #0e0b0b;
}

.category-unit-mode-toggle {
  width: min(330px, 62%);
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.single-entity-mode-choice {
  min-height: 34px;
  padding: 0 12px;
  border: 0;
  border-left: 1px solid #3d2d29;
  border-radius: 0;
  background: transparent;
  color: #897a71;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  transition: background 0.16s ease, color 0.16s ease;
}

.single-entity-mode-choice:first-child {
  border-left: 0;
}

.single-entity-mode-choice:hover:not(:disabled) {
  background: #2c211e;
  color: #f3d29a;
}

.single-entity-mode-choice.active {
  background: linear-gradient(135deg, #a76531, #c88b49);
  box-shadow: inset 0 1px 0 rgb(255 234 192 / 22%);
  color: #fff7e8;
}

.single-entity-mode-choice:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.single-entity-mode-control small {
  color: #8d7f77;
  font-size: 13px;
  line-height: 1.55;
}

.character-health-toggle {
  min-height: 62px;
  padding-top: 0;
  border-top: 0;
  border-bottom: 0;
}

.friendly-fire-card {
  min-height: min-content;
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
  font-size: 13px;
  line-height: 1.65;
}

.game-data-note p + p {
  margin-top: 5px;
}

.game-data-modal > .game-data-footer {
  flex-basis: auto;
  min-height: 72px;
  padding-top: 10px;
  padding-bottom: 10px;
}

.game-data-footer-content {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
}

.game-data-footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 9px;
}

.game-data-regeneration-warning {
  min-width: 0;
  margin: 0;
  color: #d69b65;
  font-size: 13px;
  line-height: 1.45;
  text-align: left;
}

@media (max-width: 620px) {
  .unit-scale-slider-row {
    gap: 9px;
  }

  .single-entity-mode-row {
    align-items: stretch;
    flex-direction: column;
    gap: 7px;
  }

  .single-entity-mode-toggle {
    width: 100%;
  }

  .game-data-modal > .game-data-footer {
    padding: 12px 14px;
  }

  .game-data-footer-content {
    grid-template-columns: 1fr;
    gap: 10px;
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
    grid-row: 1;
  }
}
</style>
