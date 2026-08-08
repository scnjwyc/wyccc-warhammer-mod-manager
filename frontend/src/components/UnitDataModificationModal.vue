<script setup>
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { t } from '../languages'
import { invoke } from '../bridge'

const props = defineProps({
  open: { type: Boolean, default: false },
  busy: { type: String, default: '' },
  initialSearch: { type: String, default: '' },
  gameId: { type: String, default: 'warhammer3' },
})

const emit = defineEmits(['close', 'save'])

const PAGE_SIZE = 200

const loading = ref(false)
const error = ref('')
const rows = shallowRef([])
const stats = ref({})
const search = ref('')
const page = ref(1)
const sortField = ref('')
const sortDesc = ref(false)
const draftEdits = reactive({})
const tooltip = reactive({ show: false, x: 0, y: 0, title: '', body: '', lines: [] })

const CASTE_LABELS = Object.freeze({
  chariot: 'unitData.caste.chariot',
  generic: 'unitData.caste.generic',
  hero: 'unitData.caste.hero',
  lord: 'unitData.caste.lord',
  melee_cavalry: 'unitData.caste.meleeCavalry',
  melee_infantry: 'unitData.caste.meleeInfantry',
  missile_cavalry: 'unitData.caste.missileCavalry',
  missile_infantry: 'unitData.caste.missileInfantry',
  monster: 'unitData.caste.monster',
  monstrous_cavalry: 'unitData.caste.monstrousCavalry',
  monstrous_infantry: 'unitData.caste.monstrousInfantry',
  war_beast: 'unitData.caste.warBeast',
  warmachine: 'unitData.caste.warmachine',
})

const casteLabel = caste => {
  const key = CASTE_LABELS[String(caste || '').toLowerCase()]
  return key ? t(key) : (String(caste || '') || t('unitData.caste.unknown'))
}

const COLUMNS = Object.freeze([
  { field: 'mod_name', labelKey: 'unitData.modName', width: 351, sticky: true, kind: 'modlink', helpKey: 'unitData.help.modName' },
  { field: 'name', labelKey: 'unitData.name', width: 231.66, sticky: true, kind: 'namekey', helpKey: 'unitData.help.name' },
  { field: 'race', labelKey: 'unitData.race', width: 126, kind: 'text', helpKey: 'unitData.help.race', excludeGames: ['three_kingdoms'] },
  { field: 'caste', labelKey: 'unitData.caste', width: 112, kind: 'caste', helpKey: 'unitData.help.caste' },
  { field: 'enabled', labelKey: 'unitData.enabled', width: 105, kind: 'bool', helpKey: 'unitData.help.enabled' },
  { field: 'campaign_cap', labelKey: 'unitData.campaignCap', width: 105, kind: 'number', helpKey: 'unitData.help.campaignCap' },
  { field: 'recruitment_cost', labelKey: 'unitData.recruitmentCost', width: 105, kind: 'number', helpKey: 'unitData.help.recruitmentCost' },
  { field: 'upkeep_cost', labelKey: 'unitData.upkeepCost', width: 105, kind: 'number', helpKey: 'unitData.help.upkeepCost' },
  { field: 'model_count', labelKey: 'unitData.modelCount', width: 105, kind: 'number', helpKey: 'unitData.help.modelCount' },
  { field: 'morale', labelKey: 'unitData.leadership', threeKingdomsLabelKey: 'unitData.morale', width: 105, kind: 'number', helpKey: 'unitData.help.leadership', threeKingdomsHelpKey: 'unitData.help.morale' },
  { field: 'movement_speed', labelKey: 'unitData.movementSpeed', width: 110.88, kind: 'number', step: 0.1, helpKey: 'unitData.help.movementSpeed' },
  { field: 'armour', labelKey: 'unitData.armour', width: 98, kind: 'armour', helpKey: 'unitData.help.armour' },
  { field: 'missile_block_chance', labelKey: 'unitData.missileBlockChance', width: 110.88, kind: 'number', helpKey: 'unitData.help.missileBlockChance', onlyGames: ['three_kingdoms'] },
  { field: 'hit_points', labelKey: 'unitData.hitPoints', width: 126, kind: 'number', helpKey: 'unitData.help.hitPoints' },
  { field: 'total_hp', labelKey: 'unitData.totalHp', width: 112, kind: 'readonly', helpKey: 'unitData.help.totalHp' },
  { field: 'charge_bonus', labelKey: 'unitData.chargeBonus', width: 110.88, kind: 'number', helpKey: 'unitData.help.chargeBonus' },
  { field: 'melee_attack', labelKey: 'unitData.meleeAttack', width: 110.88, kind: 'number', helpKey: 'unitData.help.meleeAttack' },
  { field: 'melee_defence', labelKey: 'unitData.meleeDefence', threeKingdomsLabelKey: 'unitData.meleeDodge', width: 110.88, kind: 'number', helpKey: 'unitData.help.meleeDefence', threeKingdomsHelpKey: 'unitData.help.meleeDodge' },
  { field: 'ammo', labelKey: 'unitData.ammo', width: 100.8, kind: 'number', helpKey: 'unitData.help.ammo' },
  { field: 'missile_resistance', labelKey: 'unitData.missileResistance', width: 110.88, kind: 'number', helpKey: 'unitData.help.missileResistance', excludeGames: ['three_kingdoms'] },
  { field: 'fire_resistance', labelKey: 'unitData.fireResistance', width: 110.88, kind: 'number', helpKey: 'unitData.help.fireResistance', excludeGames: ['three_kingdoms'] },
  { field: 'magic_resistance', labelKey: 'unitData.magicResistance', width: 110.88, kind: 'number', helpKey: 'unitData.help.magicResistance', excludeGames: ['three_kingdoms'] },
  { field: 'physical_resistance', labelKey: 'unitData.physicalResistance', width: 110.88, kind: 'number', helpKey: 'unitData.help.physicalResistance', excludeGames: ['three_kingdoms'] },
  { field: 'ward_save', labelKey: 'unitData.wardSave', width: 110.88, kind: 'number', helpKey: 'unitData.help.wardSave', excludeGames: ['three_kingdoms'] },
  { field: 'melee_damage', labelKey: 'unitData.meleeDamage', width: 126.36, kind: 'number', helpKey: 'unitData.help.meleeDamage' },
  { field: 'melee_ap_damage', labelKey: 'unitData.meleeApDamage', width: 136.89, kind: 'number', helpKey: 'unitData.help.meleeApDamage' },
  { field: 'melee_attack_speed', labelKey: 'unitData.meleeAttackSpeed', width: 126.36, kind: 'number', step: 0.1, helpKey: 'unitData.help.meleeAttackSpeed', onlyGames: ['three_kingdoms'] },
  { field: 'melee_bonus_v_cavalry', labelKey: 'unitData.meleeBonusVCavalry', width: 147.42, kind: 'number', helpKey: 'unitData.help.meleeBonusVCavalry', onlyGames: ['three_kingdoms'] },
  { field: 'melee_bonus_v_infantry', labelKey: 'unitData.meleeBonusVInfantry', width: 147.42, kind: 'number', helpKey: 'unitData.help.meleeBonusVInfantry', onlyGames: ['three_kingdoms'] },
  { field: 'missile_damage', labelKey: 'unitData.missileDamage', width: 136.89, kind: 'number', helpKey: 'unitData.help.missileDamage' },
  { field: 'missile_ap_damage', labelKey: 'unitData.missileApDamage', width: 136.89, kind: 'number', helpKey: 'unitData.help.missileApDamage' },
  { field: 'missile_bonus_v_cavalry', labelKey: 'unitData.missileBonusVCavalry', width: 147.42, kind: 'number', helpKey: 'unitData.help.missileBonusVCavalry', onlyGames: ['three_kingdoms'] },
  { field: 'missile_bonus_v_infantry', labelKey: 'unitData.missileBonusVInfantry', width: 147.42, kind: 'number', helpKey: 'unitData.help.missileBonusVInfantry', onlyGames: ['three_kingdoms'] },
  { field: 'explosion_damage', labelKey: 'unitData.explosionDamage', width: 147.42, kind: 'number', helpKey: 'unitData.help.explosionDamage', excludeGames: ['three_kingdoms'] },
  { field: 'explosion_ap_damage', labelKey: 'unitData.explosionApDamage', width: 147.42, kind: 'number', helpKey: 'unitData.help.explosionApDamage', excludeGames: ['three_kingdoms'] },
  { field: 'range', labelKey: 'unitData.range', width: 110.88, kind: 'number', helpKey: 'unitData.help.range' },
  { field: 'reload', labelKey: 'unitData.reload', width: 110.88, kind: 'number', helpKey: 'unitData.help.reload', excludeGames: ['three_kingdoms'] },
  { field: 'ranged_attack_speed', labelKey: 'unitData.rangedAttackSpeed', width: 126.36, kind: 'number', helpKey: 'unitData.help.rangedAttackSpeed', onlyGames: ['three_kingdoms'] },
  { field: 'accuracy', labelKey: 'unitData.accuracy', width: 110.88, kind: 'number', helpKey: 'unitData.help.accuracy' },
])

const EDITABLE_COLUMN_KINDS = new Set(['bool', 'armour', 'number'])
const isEditableColumn = column => EDITABLE_COLUMN_KINDS.has(column.kind)
const isThreeKingdoms = computed(() => props.gameId === 'three_kingdoms')
const visibleColumns = computed(() => COLUMNS.filter(column => (
  (!column.onlyGames || column.onlyGames.includes(props.gameId))
  && (!column.excludeGames || !column.excludeGames.includes(props.gameId))
)))
const editableColumnTone = column => {
  const editableIndex = visibleColumns.value
    .filter(isEditableColumn)
    .findIndex(candidate => candidate.field === column.field)
  return editableIndex >= 0 && editableIndex % 2 === 0 ? 'even' : 'odd'
}
const columnLabelKey = column => (
  isThreeKingdoms.value && column.threeKingdomsLabelKey
    ? column.threeKingdomsLabelKey
    : column.labelKey
)
const columnHelpKey = column => (
  isThreeKingdoms.value && column.threeKingdomsHelpKey
    ? column.threeKingdomsHelpKey
    : column.helpKey
)

const tableWidth = computed(() => (
  visibleColumns.value.reduce((total, column) => total + column.width, 0)
))

const cellStyle = column => {
  const width = `${column.width}px`
  const style = { width, minWidth: width, maxWidth: width }
  if (column.sticky) {
    let left = 0
    for (const candidate of visibleColumns.value) {
      if (candidate.field === column.field) break
      if (candidate.sticky) left += candidate.width
    }
    style.left = `${left}px`
  }
  return style
}

const filteredRows = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return rows.value
  return rows.value.filter(row => (
    String(row.mod_name || '').toLowerCase().includes(query)
    || (Array.isArray(row.source_chain)
      && row.source_chain.some(source => String(source || '').toLowerCase().includes(query)))
    || String(row.key || '').toLowerCase().includes(query)
    || String(row.name || '').toLowerCase().includes(query)
    || String(row.race || '').toLowerCase().includes(query)
    || casteLabel(row.caste).toLowerCase().includes(query)
  ))
})

const sortValue = (row, column) => {
  if (column.field === 'caste') return casteLabel(row.caste)
  if (column.field === 'armour') return Number(row.armour_value || 0)
  const value = row[column.field]
  return typeof value === 'number' ? value : String(value || '')
}

const sortedRows = computed(() => {
  const result = filteredRows.value
  if (!sortField.value) return result
  const column = COLUMNS.find(item => item.field === sortField.value)
  if (!column) return result
  const direction = sortDesc.value ? -1 : 1
  return [...result].sort((a, b) => {
    const av = sortValue(a, column)
    const bv = sortValue(b, column)
    if (av < bv) return -1 * direction
    if (av > bv) return 1 * direction
    return 0
  })
})

const totalPages = computed(() => (
  Math.max(1, Math.ceil(sortedRows.value.length / PAGE_SIZE))
))

const pageRows = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return sortedRows.value.slice(start, start + PAGE_SIZE)
})

watch(
  () => [search.value, sortField.value, sortDesc.value],
  () => { page.value = 1 },
)

watch(
  () => props.gameId,
  () => {
    if (!visibleColumns.value.some(column => column.field === sortField.value)) {
      sortField.value = ''
    }
  },
)

watch(totalPages, pages => {
  if (page.value > pages) page.value = pages
})

const editedCount = computed(() => Object.keys(draftEdits).length)

const resetDraft = () => {
  for (const key of Object.keys(draftEdits)) delete draftEdits[key]
  for (const row of rows.value) {
    if (row.edited && typeof row.edited === 'object' && Object.keys(row.edited).length) {
      draftEdits[row.key] = { ...row.edited }
    }
  }
}

const isRowEdited = row => (
  Boolean(draftEdits[row.key] && Object.keys(draftEdits[row.key]).length)
)

const isFieldEdited = (row, field) => (
  Boolean(
    draftEdits[row.key]
    && Object.prototype.hasOwnProperty.call(draftEdits[row.key], field),
  )
)

const originalValue = (row, field) => {
  if (row.original_values && Object.prototype.hasOwnProperty.call(row.original_values, field)) {
    return row.original_values[field]
  }
  if (field === 'armour') return row.armour_value
  return row[field]
}

const ONE_DECIMAL_FIELDS = new Set(['movement_speed', 'melee_attack_speed'])
const NORMALIZE_ONE_DECIMAL_FIELDS = new Set(['melee_attack_speed'])

const formatOneDecimal = value => {
  if (value === null || value === undefined || value === '') return value
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(1) : String(value)
}

const displayOriginalValue = (value, field = '') => {
  if (value === null || value === undefined || value === '') return '—'
  return ONE_DECIMAL_FIELDS.has(field) ? formatOneDecimal(value) : String(value)
}

const cellValue = (row, field) => {
  const draft = draftEdits[row.key]
  return draft && field in draft ? draft[field] : row[field]
}

const displayCellValue = (row, column) => (
  ONE_DECIMAL_FIELDS.has(column.field)
    ? formatOneDecimal(cellValue(row, column.field))
    : cellValue(row, column.field)
)

const armourValue = row => {
  const draft = draftEdits[row.key]
  return draft && 'armour' in draft ? draft.armour : row.armour_value
}

const fieldLocked = (row, field) => {
  if (field === 'model_count') return Boolean(row.model_count_locked)
  if (field === 'hit_points') return Boolean(row.hit_points_locked)
  if (field === 'enabled') return Boolean(row.enabled_locked)
  if (field === 'missile_block_chance') return Boolean(row.missile_block_chance_locked)
  if (field === 'movement_speed') return Boolean(row.movement_speed_locked)
  if (field === 'melee_attack_speed') return Boolean(row.melee_attack_speed_locked)
  if (field === 'ranged_attack_speed') return Boolean(row.ranged_attack_speed_locked)
  return false
}

const setCell = (row, field, value) => {
  draftEdits[row.key] = {
    ...(draftEdits[row.key] || {}),
    [field]: value,
  }
}

const setNumericCell = (row, field, event) => {
  const raw = event.target.value
  if (raw === '') {
    setCell(row, field, '')
    return
  }
  const numeric = Number(raw)
  setCell(
    row,
    field,
    NORMALIZE_ONE_DECIMAL_FIELDS.has(field) && Number.isFinite(numeric)
      ? Number(numeric.toFixed(1))
      : numeric,
  )
}

const clearAllEdits = () => {
  for (const key of Object.keys(draftEdits)) delete draftEdits[key]
}

const removeFieldEdit = (row, field) => {
  const current = draftEdits[row.key]
  if (!current) return
  const next = { ...current }
  delete next[field]
  if (Object.keys(next).length) draftEdits[row.key] = next
  else delete draftEdits[row.key]
}

const effectiveTotalHp = row => {
  if (row.hit_points_locked) return row.total_hp
  const draft = draftEdits[row.key]
  if (!draft || (!('hit_points' in draft) && !('model_count' in draft))) return row.total_hp
  const hp = Number(cellValue(row, 'hit_points') ?? 0)
  const models = Math.max(1, Number(cellValue(row, 'model_count') ?? 1) || 1)
  return hp * models
}

const toggleSort = column => {
  if (sortField.value === column.field) sortDesc.value = !sortDesc.value
  else {
    sortField.value = column.field
    sortDesc.value = false
  }
}

const showHoverTooltip = (event, { title = '', body = '', lines = [] } = {}) => {
  const rect = event.currentTarget.getBoundingClientRect()
  tooltip.show = true
  tooltip.title = title
  tooltip.body = body
  tooltip.lines = lines
  tooltip.x = Math.max(8, Math.min(rect.left, window.innerWidth - 420))
  tooltip.y = Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - 170))
}

const hideHoverTooltip = () => {
  tooltip.show = false
}

const showOriginalValueTooltip = (event, row, column) => {
  if (!isFieldEdited(row, column.field)) return
  showHoverTooltip(event, {
    title: t('unitData.originalValueTitle', { field: t(columnLabelKey(column)) }),
    body: t('unitData.originalValue', {
      value: displayOriginalValue(originalValue(row, column.field), column.field),
    }),
  })
}

const removeUnitEdits = (row, event) => {
  if (event?.shiftKey) {
    const modName = String(row.mod_name || '')
    for (const candidate of rows.value) {
      if (String(candidate.mod_name || '') === modName) delete draftEdits[candidate.key]
    }
    return
  }
  delete draftEdits[row.key]
}

const modifiedByCount = row => (
  Math.max(0, (row.source_chain || []).length - 1)
)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const data = await invoke('get_unit_data_list')
    rows.value = data.units || []
    stats.value = data.stats || {}
    page.value = 1
    resetDraft()
  } catch (err) {
    error.value = String(err?.message || err)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  open => {
    if (open) {
      search.value = String(props.initialSearch || '')
      void load()
    }
  },
)

watch(
  () => props.initialSearch,
  value => {
    if (props.open) search.value = String(value || '')
  },
)

const submit = () => {
  const payload = {}
  for (const [key, fields] of Object.entries(draftEdits)) {
    if (fields && Object.keys(fields).length) payload[key] = fields
  }
  emit('save', payload)
}
</script>

<template>
  <div v-if="open" class="modal-backdrop unit-data-backdrop" @mousedown.self="emit('close')">
    <div class="modal-card unit-data-modal" role="dialog" aria-modal="true" :aria-label="t('unitData.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('unitData.eyebrow') }}</span>
          <h2>{{ t('unitData.title') }}</h2>
        </div>
        <button type="button" class="icon-button" :aria-label="t('common.close')" @click="emit('close')">×</button>
      </header>

      <div class="modal-body unit-data-body">
        <p class="unit-data-intro">{{ t('unitData.intro') }}</p>

        <div class="unit-data-toolbar">
          <input
            v-model="search"
            class="unit-data-search"
            type="search"
            :placeholder="t('unitData.searchPlaceholder')"
            data-testid="unit-data-search"
          />
          <span class="unit-data-count" data-testid="unit-data-count">
            {{ t('unitData.count', { shown: filteredRows.length, total: rows.length, edited: editedCount }) }}
          </span>
        </div>

        <p v-if="error" class="unit-data-error" data-testid="unit-data-error">{{ error }}</p>
        <p v-else-if="loading" class="unit-data-loading" data-testid="unit-data-loading">
          <span class="spinner"></span> {{ t('unitData.loading') }}
        </p>

        <div v-else class="unit-data-table-wrap">
          <table class="unit-data-table" :style="{ width: `${tableWidth}px` }">
            <colgroup>
              <col
                v-for="column in visibleColumns"
                :key="`col-${column.field}`"
                :style="{ width: `${column.width}px` }"
              />
            </colgroup>
            <thead>
              <tr>
                <th
                  v-for="column in visibleColumns"
                  :key="column.field"
                  class="unit-data-th"
                  :class="{
                    'unit-data-sticky': column.sticky,
                    'unit-data-sorted': sortField === column.field,
                  }"
                  :style="cellStyle(column)"
                  :data-testid="`unit-data-header-${column.field}`"
                >
                  <span class="unit-data-th-label" role="button" tabindex="0" :title="t(columnLabelKey(column))" @click="toggleSort(column)" @keydown.enter="toggleSort(column)">
                    {{ t(columnLabelKey(column)) }}
                    <span v-if="sortField === column.field" class="unit-data-sort-mark">
                      {{ sortDesc ? '↓' : '↑' }}
                    </span>
                  </span>
                  <button
                    type="button"
                    class="unit-data-info"
                    :aria-label="t('unitData.infoTitle')"
                    :data-testid="`unit-data-help-${column.field}`"
                    @mouseenter="showHoverTooltip($event, { title: `${t('unitData.infoTitle')}：${t(columnLabelKey(column))}`, body: t(columnHelpKey(column)) })"
                    @mouseleave="hideHoverTooltip"
                    @focus="showHoverTooltip($event, { title: `${t('unitData.infoTitle')}：${t(columnLabelKey(column))}`, body: t(columnHelpKey(column)) })"
                    @blur="hideHoverTooltip"
                  >!</button>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in pageRows" :key="row.key" v-memo="[row, draftEdits[row.key]]" class="unit-data-row">
                <td
                  v-for="column in visibleColumns"
                  :key="column.field"
                  class="unit-data-td"
                  :class="{
                    'unit-data-sticky': column.sticky,
                    'unit-data-editable': isEditableColumn(column),
                    'unit-data-editable-even': editableColumnTone(column) === 'even',
                    'unit-data-editable-odd': editableColumnTone(column) === 'odd',
                    'unit-data-edited-cell': isFieldEdited(row, column.field),
                    'unit-data-readonly': column.kind === 'readonly' || column.field === 'mod_name' || column.field === 'name' || column.field === 'race' || column.field === 'caste',
                    'unit-data-disabled-row': cellValue(row, 'enabled') === false,
                  }"
                  :style="cellStyle(column)"
                >
                  <template v-if="column.kind === 'modlink'">
                    <a
                      v-if="modifiedByCount(row) > 0"
                      href="#"
                      class="unit-data-modlink"
                      :title="t('unitData.sourceChainTitle')"
                      :data-testid="`unit-source-chain-${row.key}`"
                      @mouseenter="showHoverTooltip($event, { title: t('unitData.sourceChainTitle'), body: t('unitData.sourceChainIntro'), lines: row.source_chain })"
                      @mouseleave="hideHoverTooltip"
                    >{{ row.mod_name }}</a>
                    <span v-else class="unit-data-text">{{ row.mod_name }}</span>
                    <span v-if="modifiedByCount(row) > 0" class="unit-data-modified">
                      {{ t('unitData.modified', { count: modifiedByCount(row) }) }}
                    </span>
                  </template>
                  <template v-else-if="column.kind === 'namekey'">
                    <span class="unit-data-name-line">
                      <button
                        v-if="isRowEdited(row)"
                        type="button"
                        class="unit-data-remove"
                        :aria-label="t('unitData.removeUnitTitle')"
                        :data-testid="`unit-remove-edits-${row.key}`"
                        @click.stop="removeUnitEdits(row, $event)"
                        @mouseenter="showHoverTooltip($event, { title: t('unitData.removeUnitTitle'), body: t('unitData.removeUnitHelp') })"
                        @mouseleave="hideHoverTooltip"
                        @focus="showHoverTooltip($event, { title: t('unitData.removeUnitTitle'), body: t('unitData.removeUnitHelp') })"
                        @blur="hideHoverTooltip"
                      >×</button>
                      <span class="unit-data-name" :class="{ 'unit-data-name-edited': isRowEdited(row) }" :title="row.name">{{ row.name }}</span>
                    </span>
                    <span class="unit-data-keytag" :title="row.key">{{ row.key }}</span>
                  </template>
                  <template v-else-if="column.kind === 'caste'">
                    <span class="unit-data-text">{{ casteLabel(row.caste) }}</span>
                  </template>
                  <span v-else-if="column.kind === 'bool'" class="unit-data-editable-content">
                    <input
                      type="checkbox"
                      class="unit-data-checkbox"
                      :class="{ 'unit-data-edited-control': isFieldEdited(row, column.field) }"
                      :checked="cellValue(row, 'enabled') !== false"
                      :disabled="!!busy || fieldLocked(row, column.field)"
                      :aria-label="t('unitData.enabled')"
                      :data-testid="`unit-enabled-${row.key}`"
                      @mouseenter="showOriginalValueTooltip($event, row, column)"
                      @mouseleave="hideHoverTooltip"
                      @change="setCell(row, 'enabled', $event.target.checked)"
                    />
                    <button
                      v-if="isFieldEdited(row, column.field)"
                      type="button"
                      class="unit-data-field-remove"
                      :aria-label="t('unitData.removeFieldTitle')"
                      :data-testid="`unit-field-remove-${column.field}-${row.key}`"
                      @click.stop="removeFieldEdit(row, column.field)"
                      @mouseenter="showHoverTooltip($event, { title: t('unitData.removeFieldTitle'), body: t('unitData.removeFieldHelp') })"
                      @mouseleave="hideHoverTooltip"
                      @focus="showHoverTooltip($event, { title: t('unitData.removeFieldTitle'), body: t('unitData.removeFieldHelp') })"
                      @blur="hideHoverTooltip"
                    >×</button>
                  </span>
                  <span v-else-if="column.kind === 'armour'" class="unit-data-editable-content">
                    <select
                      class="unit-data-select"
                      :class="{ 'unit-data-edited-control': isFieldEdited(row, column.field) }"
                      :value="armourValue(row)"
                      :disabled="!!busy || !(row.armour_options && row.armour_options.length)"
                      :aria-label="t('unitData.armour')"
                      @mouseenter="showOriginalValueTooltip($event, row, column)"
                      @mouseleave="hideHoverTooltip"
                      @change="setCell(row, 'armour', Number($event.target.value))"
                    >
                      <option
                        v-for="option in row.armour_options || []"
                        :key="option"
                        :value="option"
                      >
                        {{ option }}
                      </option>
                    </select>
                    <button
                      v-if="isFieldEdited(row, column.field)"
                      type="button"
                      class="unit-data-field-remove"
                      :aria-label="t('unitData.removeFieldTitle')"
                      :data-testid="`unit-field-remove-${column.field}-${row.key}`"
                      @click.stop="removeFieldEdit(row, column.field)"
                      @mouseenter="showHoverTooltip($event, { title: t('unitData.removeFieldTitle'), body: t('unitData.removeFieldHelp') })"
                      @mouseleave="hideHoverTooltip"
                      @focus="showHoverTooltip($event, { title: t('unitData.removeFieldTitle'), body: t('unitData.removeFieldHelp') })"
                      @blur="hideHoverTooltip"
                    >×</button>
                  </span>
                  <span v-else-if="column.kind === 'number'" class="unit-data-editable-content">
                    <input
                      type="number"
                      class="unit-data-input"
                      :class="{ 'unit-data-edited-control': isFieldEdited(row, column.field) }"
                      :value="displayCellValue(row, column)"
                      :step="column.step || 1"
                      :disabled="!!busy || fieldLocked(row, column.field)"
                      :data-testid="`unit-${column.field}-${row.key}`"
                      @mouseenter="showOriginalValueTooltip($event, row, column)"
                      @mouseleave="hideHoverTooltip"
                      @input="setNumericCell(row, column.field, $event)"
                    />
                    <button
                      v-if="isFieldEdited(row, column.field)"
                      type="button"
                      class="unit-data-field-remove"
                      :aria-label="t('unitData.removeFieldTitle')"
                      :data-testid="`unit-field-remove-${column.field}-${row.key}`"
                      @click.stop="removeFieldEdit(row, column.field)"
                      @mouseenter="showHoverTooltip($event, { title: t('unitData.removeFieldTitle'), body: t('unitData.removeFieldHelp') })"
                      @mouseleave="hideHoverTooltip"
                      @focus="showHoverTooltip($event, { title: t('unitData.removeFieldTitle'), body: t('unitData.removeFieldHelp') })"
                      @blur="hideHoverTooltip"
                    >×</button>
                  </span>
                  <span v-else-if="column.kind === 'readonly'" class="unit-data-ro" :data-testid="`unit-total-hp-${row.key}`">
                    {{ effectiveTotalHp(row) }}
                  </span>
                  <span v-else class="unit-data-text">{{ cellValue(row, column.field) }}</span>
                </td>
              </tr>
            </tbody>
          </table>

          <div
            v-if="tooltip.show"
            class="unit-data-tooltip"
            :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
            data-testid="unit-data-tooltip"
          >
            <strong v-if="tooltip.title">{{ tooltip.title }}</strong>
            <p v-if="tooltip.body">{{ tooltip.body }}</p>
            <ol v-if="tooltip.lines && tooltip.lines.length" class="unit-data-chain-list">
              <li v-for="(name, index) in tooltip.lines" :key="`${name}-${index}`">{{ name }}</li>
            </ol>
          </div>
        </div>

        <div class="unit-data-pager">
          <button
            type="button"
            class="secondary-button compact"
            :disabled="page <= 1"
            data-testid="unit-data-prev"
            @click="page -= 1"
          >{{ t('unitData.prevPage') }}</button>
          <span class="unit-data-page-info" data-testid="unit-data-page-info">
            {{ t('unitData.pageInfo', { page, pages: totalPages }) }}
          </span>
          <button
            type="button"
            class="secondary-button compact"
            :disabled="page >= totalPages"
            data-testid="unit-data-next"
            @click="page += 1"
          >{{ t('unitData.nextPage') }}</button>
        </div>
      </div>

      <footer class="modal-footer">
        <button
          type="button"
          class="danger-button compact unit-data-clear-all"
          :disabled="!!busy || loading || !editedCount"
          data-testid="unit-data-clear-all"
          @click="clearAllEdits"
        >
          {{ t('unitData.clearAll') }}
        </button>
        <span v-if="busy" class="unit-data-busy">{{ busy }}</span>
        <button type="button" class="secondary-button" :disabled="!!busy || loading" @click="emit('close')">
          {{ t('common.cancel') }}
        </button>
        <button
          type="button"
          class="primary-button"
          :disabled="!!busy || loading"
          data-testid="unit-data-save"
          @click="submit"
        >
          {{ t('unitData.save') }}
        </button>
      </footer>
    </div>
  </div>
</template>
