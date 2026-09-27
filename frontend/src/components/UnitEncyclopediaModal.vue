<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { invoke } from '../bridge'
import { currentLocale, t } from '../languages'

const props = defineProps({ open: Boolean, suspended: Boolean, editDisabled: Boolean, refreshKey: Number })
const emit = defineEmits(['close', 'edit-unit'])
const catalogue = ref(null)
const loading = ref(false)
const error = ref('')
const imageError = ref(false)
const images = ref({})
const raceKey = ref('')
const unitKey = ref('')
const search = ref('')
const rosterPage = ref('characters')
const dialog = ref(null)
const list = ref(null)
let generation = 0
let requested = new Set()
let restoreFocus = null

const image = path => images.value[path] || ''
const art = name => image(catalogue.value?.art?.[name])
const texture = name => art(name) ? { backgroundImage: `url("${art(name)}")` } : {}
const format = value => value == null ? '—' : Number(value).toLocaleString(currentLocale(), { maximumFractionDigits: 1 })
const raceName = race => race?.key === 'unassigned' ? t('encyclopedia.unassigned')
  : race?.prologue ? t('encyclopedia.prologueName', { name: race.name }) : race?.name || ''
const selectedRace = computed(() => catalogue.value?.races.find(r => r.key === raceKey.value))
const filteredRaces = computed(() => (catalogue.value?.races || []).filter(r => (
  `${raceName(r)} ${r.key}`.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
)))
const raceUnits = computed(() => (catalogue.value?.units || []).filter(u => u.races.includes(raceKey.value)))
const filteredUnits = computed(() => raceUnits.value.filter(u => (
  `${u.name} ${u.key} ${u.category}`.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
)))
const groupOrder = ['lord', 'hero', 'infantry', 'missile_infantry', 'cavalry_chariots', 'monsters', 'artillery_war_machines']
const sortedUnits = computed(() => [...filteredUnits.value].sort((a, b) => {
  const rank = key => groupOrder.includes(key) ? groupOrder.indexOf(key) : groupOrder.length
  return rank(a.group) - rank(b.group) || a.group.localeCompare(b.group) || a.recruitment_cost - b.recruitment_cost
}))
const isCharacter = unit => ['lord', 'hero'].includes(unit.caste)
const rosterPages = computed(() => [
  { key: 'characters', label: t('encyclopedia.characters'), count: filteredUnits.value.filter(isCharacter).length },
  { key: 'units', label: t('encyclopedia.regularUnits'), count: filteredUnits.value.filter(u => !isCharacter(u)).length },
])
const visibleUnits = computed(() => sortedUnits.value.filter(u => isCharacter(u) === (rosterPage.value === 'characters')))
const groups = computed(() => {
  const result = []
  for (const unit of visibleUnits.value) {
    let group = result.find(item => item.key === unit.group)
    if (!group) {
      group = { key: unit.group, name: unit.group_name || groupLabel(unit.group), units: [] }
      result.push(group)
    }
    group.units.push(unit)
  }
  return result
})
function groupLabel(key) {
  const labels = {
    lord: 'lords', hero: 'heroes', infantry: 'infantry', melee_infantry: 'infantry',
    missile_infantry: 'missileInfantry', cavalry_chariots: 'cavalry', cavalry: 'cavalry',
    melee_cavalry: 'cavalry', missile_cavalry: 'cavalry', chariot: 'cavalry',
    monsters: 'monsters', monstrous_infantry: 'monsters', monster: 'monsters',
    artillery_war_machines: 'artillery', warmachine: 'artillery', artillery: 'artillery',
  }
  return t(`encyclopedia.${labels[key] || 'other'}`)
}
const selectedUnit = computed(() => raceUnits.value.find(u => u.key === unitKey.value))
const statRows = computed(() => {
  const u = selectedUnit.value
  if (!u) return []
  const rows = [
    ['model_count', 'encyclopedia.models', 200], ['armour_value', 'unitData.armour', 200],
    ['morale', 'unitData.leadership', 120], ['speed', 'unitData.movementSpeed', 120],
    ['melee_attack', 'unitData.meleeAttack', 100], ['melee_defence', 'unitData.meleeDefence', 100],
    ['weapon_strength', 'encyclopedia.weaponStrength', 700], ['charge_bonus', 'unitData.chargeBonus', 100],
  ]
  if (u.range > 0) rows.push(
    ['ammo', 'unitData.ammo', 60], ['range', 'unitData.range', 500],
    ['missile_strength', 'encyclopedia.missileStrength', 150],
  )
  return rows.map(([key, label, max]) => ({
    key, label: t(label), value: u[key], percent: Math.min(100, Math.max(0, Number(u[key] || 0) / max * 100)),
    icon: art(key === 'missile_strength' ? 'missile_damage' : key),
  }))
})
const resistances = computed(() => ['shield', 'physical_resistance', 'missile_resistance', 'magic_resistance', 'fire_resistance', 'ward_save']
  .filter(key => selectedUnit.value?.[key]).map(key => ({ key, value: selectedUnit.value[key], label: t({
    shield: 'unitData.missileBlockChance', physical_resistance: 'unitData.physicalResistance',
    missile_resistance: 'unitData.missileResistance', magic_resistance: 'unitData.magicResistance',
    fire_resistance: 'unitData.fireResistance', ward_save: 'unitData.wardSave',
  }[key]) })))
const visibleAssets = computed(() => {
  if (!props.open || !catalogue.value) return []
  const paths = Object.values(catalogue.value.art || {})
  if (!raceKey.value) {
    for (const race of filteredRaces.value) paths.push(race.image, race.crest)
  } else {
    paths.push(selectedRace.value?.crest)
    if (selectedUnit.value) paths.push(selectedUnit.value.portrait, selectedUnit.value.category_icon,
      ...selectedUnit.value.features.map(f => f.icon))
    for (const unit of visibleUnits.value) paths.push(unit.icon)
  }
  return [...new Set(paths.filter(Boolean))]
})

async function requestImages() {
  const run = generation
  const token = catalogue.value?.token
  if (!token) return
  const missing = visibleAssets.value.filter(path => !requested.has(path))
  missing.forEach(path => requested.add(path))
  for (let start = 0; start < missing.length; start += 48) {
    if (run !== generation) return
    const batch = missing.slice(start, start + 48)
    try {
      const result = await invoke('get_unit_encyclopedia_images', token, batch)
      if (run !== generation) return
      images.value = { ...images.value, ...result }
    } catch {
      if (run !== generation) return
      batch.forEach(path => requested.delete(path))
      imageError.value = true
    }
  }
}
watch(visibleAssets, requestImages)

async function load(preserveSelection = false) {
  const run = ++generation
  const scrollTop = preserveSelection ? list.value?.scrollTop || 0 : 0
  loading.value = true
  error.value = ''
  imageError.value = false
  catalogue.value = null
  images.value = {}
  requested = new Set()
  if (!preserveSelection) {
    raceKey.value = ''
    unitKey.value = ''
    search.value = ''
    rosterPage.value = 'characters'
  }
  try {
    const result = await invoke('get_unit_encyclopedia')
    if (run === generation && props.open) {
      catalogue.value = result
      if (preserveSelection && raceKey.value) {
        if (!selectedRace.value) back()
        else {
          if (!selectedUnit.value) unitKey.value = visibleUnits.value[0]?.key || ''
        }
      }
    }
  } catch (err) {
    if (run === generation) error.value = err.message || String(err)
  } finally {
    if (run === generation) {
      loading.value = false
      await nextTick()
      if (list.value) list.value.scrollTop = scrollTop
    }
  }
}
watch(() => props.refreshKey, () => { if (props.open) void load(true) })
watch(() => props.suspended, async suspended => {
  if (!suspended && props.open) {
    await nextTick()
    const editButton = dialog.value?.querySelector('[data-testid="encyclopedia-edit-unit"]')
    ;(editButton || dialog.value)?.focus()
  }
})
function chooseRace(race) {
  raceKey.value = race.key
  search.value = ''
  choosePage(raceUnits.value.some(isCharacter) ? 'characters' : 'units')
  void nextTick(() => dialog.value?.focus())
}
function back() {
  raceKey.value = ''
  search.value = ''
  unitKey.value = ''
  rosterPage.value = 'characters'
  void nextTick(() => dialog.value?.focus())
}
function choosePage(key) {
  rosterPage.value = key
  unitKey.value = visibleUnits.value[0]?.key || ''
  if (list.value) list.value.scrollTop = 0
}
watch(search, () => {
  if (!raceKey.value) return
  const matches = rosterPages.value.find(p => p.key === rosterPage.value)?.count
  const nextPage = matches ? rosterPage.value : rosterPages.value.find(p => p.count)?.key || rosterPage.value
  choosePage(nextPage)
})
watch(() => props.open, async open => {
  if (open) {
    restoreFocus = document.activeElement
    void load()
    await nextTick()
    dialog.value?.focus()
  } else {
    generation += 1
    catalogue.value = null
    images.value = {}
    restoreFocus?.focus?.()
  }
}, { immediate: true })
function onKeydown(event) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    if (raceKey.value) back()
    else emit('close')
  }
  if (event.key !== 'Tab') return
  const controls = [...dialog.value.querySelectorAll('button:not(:disabled), input, [tabindex="0"]')]
    .filter(element => element.getClientRects().length)
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}
onBeforeUnmount(() => { generation += 1 })
</script>

<template>
  <div v-if="open" v-show="!suspended" class="modal-backdrop encyclopedia-backdrop">
    <section ref="dialog" class="encyclopedia" role="dialog" aria-modal="true" :aria-label="t('encyclopedia.title')" tabindex="-1" @keydown="onKeydown">
      <header class="encyclopedia-header">
        <div class="encyclopedia-heading">
          <span class="encyclopedia-kicker">TOTAL WAR · WARHAMMER III</span>
          <h2>{{ t('encyclopedia.title') }}</h2>
        </div>
        <span v-if="catalogue" class="encyclopedia-source" :title="catalogue.source_pack_names.join('\n')">
          {{ t('encyclopedia.sources', { count: catalogue.source_count }) }}
        </span>
        <button type="button" class="encyclopedia-action" :disabled="loading" @click="load()">{{ t('encyclopedia.refresh') }}</button>
        <button type="button" class="encyclopedia-close" :aria-label="t('common.close')" @click="emit('close')">×</button>
      </header>

      <div v-if="loading" class="encyclopedia-state" role="status"><span class="spinner" />{{ t('encyclopedia.loading') }}</div>
      <div v-else-if="error" class="encyclopedia-state" role="alert"><p>{{ error }}</p><button class="encyclopedia-action" @click="load()">{{ t('encyclopedia.retry') }}</button></div>
      <template v-else-if="catalogue">
        <nav class="encyclopedia-toolbar" :aria-label="t('encyclopedia.navigation')">
          <button v-if="raceKey" type="button" class="encyclopedia-action" @click="back">‹ {{ t('encyclopedia.back') }}</button>
          <span class="encyclopedia-breadcrumb">{{ raceKey ? raceName(selectedRace) : t('encyclopedia.chooseFaction') }}</span>
          <input v-model="search" type="search" :aria-label="t('encyclopedia.search')" :placeholder="raceKey ? t('encyclopedia.searchUnits') : t('encyclopedia.searchFactions')">
          <span>{{ t('encyclopedia.count', { count: raceKey ? filteredUnits.length : catalogue.units.length }) }}</span>
        </nav>
        <div v-if="imageError || catalogue.asset_warnings?.length" class="encyclopedia-image-warning" role="status">
          {{ t('encyclopedia.imageWarning') }}
          <button v-if="imageError" class="encyclopedia-action" @click="imageError = false; requestImages()">{{ t('encyclopedia.retry') }}</button>
        </div>

        <div v-if="!raceKey" class="encyclopedia-factions">
          <button v-for="race in filteredRaces" :key="race.key" type="button" class="encyclopedia-faction" :data-race="race.key" @click="chooseRace(race)">
            <img v-if="image(race.image)" class="encyclopedia-faction-art" :src="image(race.image)" alt="">
            <div class="encyclopedia-faction-shade" />
            <img v-if="image(race.crest)" class="encyclopedia-crest" :src="image(race.crest)" alt="">
            <div class="encyclopedia-faction-label"><strong>{{ raceName(race) }}</strong><span>{{ t('encyclopedia.count', { count: race.count }) }} <b>›</b></span></div>
          </button>
          <p v-if="!filteredRaces.length" class="encyclopedia-empty">{{ t('encyclopedia.empty') }}</p>
        </div>

        <div v-else class="encyclopedia-roster">
          <aside class="encyclopedia-detail" :style="texture('parchment_texture')" :aria-label="t('encyclopedia.detail')">
            <template v-if="selectedUnit">
              <div class="encyclopedia-portrait">
                <img v-if="image(selectedUnit.portrait)" :src="image(selectedUnit.portrait)" :alt="selectedUnit.name">
                <span v-else class="encyclopedia-portrait-placeholder">{{ selectedUnit.name.slice(0, 1) }}</span>
              </div>
              <div class="encyclopedia-detail-copy">
                <div class="encyclopedia-detail-title">
                  <h3>{{ selectedUnit.name }}</h3>
                  <button type="button" class="encyclopedia-edit" data-testid="encyclopedia-edit-unit"
                    :disabled="editDisabled" :title="t('encyclopedia.editUnit', { name: selectedUnit.name })"
                    :aria-label="t('encyclopedia.editUnit', { name: selectedUnit.name })"
                    @click="emit('edit-unit', selectedUnit.key, catalogue.token)">{{ t('encyclopedia.edit') }}</button>
                </div>
                <div class="encyclopedia-category"><img v-if="image(selectedUnit.category_icon)" :src="image(selectedUnit.category_icon)" alt="">{{ selectedUnit.category || groupLabel(selectedUnit.group) }}</div>
                <p v-if="selectedUnit.description" class="encyclopedia-description">{{ selectedUnit.description }}</p>
                <div class="encyclopedia-cost"><span>{{ t('unitData.recruitmentCost') }} <b>{{ format(selectedUnit.recruitment_cost) }}</b></span><span>{{ t('unitData.upkeepCost') }} <b>{{ format(selectedUnit.upkeep_cost) }}</b></span></div>
                <div class="encyclopedia-health" :aria-label="`${t('unitData.totalHp')} ${format(selectedUnit.health)}`"><img v-if="art('health')" :src="art('health')" alt=""><b>{{ format(selectedUnit.health) }}</b></div>
                <dl class="encyclopedia-stats">
                  <div v-for="stat in statRows" :key="stat.key" class="encyclopedia-stat" :data-stat="stat.key">
                    <dt><img v-if="stat.icon" :src="stat.icon" alt=""><span>{{ stat.label }}</span></dt>
                    <dd>{{ format(stat.value) }}</dd><span class="encyclopedia-stat-track"><i :style="{ width: `${stat.percent}%` }" /></span>
                  </div>
                </dl>
                <div class="encyclopedia-damage-breakdown">
                  {{ t('encyclopedia.damageParts', { base: format(selectedUnit.melee_damage), ap: format(selectedUnit.melee_ap_damage) }) }}
                  <span v-if="selectedUnit.range > 0">{{ t('encyclopedia.rangedParts', { base: format(selectedUnit.missile_damage), ap: format(selectedUnit.missile_ap_damage) }) }}</span>
                  <template v-if="selectedUnit.range > 0">
                    <span data-testid="firing-interval" :title="t('encyclopedia.firingIntervalHelp')">{{ t('encyclopedia.firingInterval') }} <b>{{ t('encyclopedia.seconds', { value: format(selectedUnit.firing_interval) }) }}</b></span>
                    <span data-testid="projectile-count" :title="t('encyclopedia.projectileCountHelp')">{{ t('encyclopedia.projectileCount') }} <b>{{ format(selectedUnit.projectile_count) }}</b></span>
                  </template>
                </div>
                <div v-if="resistances.length" class="encyclopedia-resistances"><span v-for="resistance in resistances" :key="resistance.key">{{ resistance.label }} <b>{{ resistance.value }}%</b></span></div>
                <h4 v-if="selectedUnit.features.length">{{ t('encyclopedia.features') }}</h4>
                <ul class="encyclopedia-features"><li v-for="feature in selectedUnit.features" :key="feature.key" :title="feature.description"><img v-if="image(feature.icon)" :src="image(feature.icon)" alt=""><span>{{ feature.name }}</span></li></ul>
                <details class="encyclopedia-origin"><summary>{{ t('encyclopedia.source') }}</summary><p>{{ selectedUnit.source_chain.join(' → ') }}</p><p v-if="selectedUnit.edited">{{ t('encyclopedia.edited') }}</p><code>{{ selectedUnit.key }}</code></details>
              </div>
            </template>
            <p v-else class="encyclopedia-empty">{{ t('encyclopedia.selectUnit') }}</p>
          </aside>
          <div class="encyclopedia-units-area">
            <div class="encyclopedia-roster-tabs" role="tablist" :aria-label="t('encyclopedia.rosterPages')">
              <button v-for="tab in rosterPages" :key="tab.key" type="button" class="encyclopedia-action" role="tab"
                :id="`roster-tab-${tab.key}`" :data-roster="tab.key" :aria-selected="rosterPage === tab.key"
                aria-controls="encyclopedia-roster-list" @click="choosePage(tab.key)">{{ tab.label }} <span>{{ tab.count }}</span></button>
            </div>
            <div ref="list" class="encyclopedia-units" id="encyclopedia-roster-list" role="tabpanel" :aria-labelledby="`roster-tab-${rosterPage}`">
              <section v-for="group in groups" :key="group.key" class="encyclopedia-group">
                <h3>{{ group.name }}</h3>
                <div class="encyclopedia-cards">
                  <button v-for="unit in group.units" :key="unit.key" type="button" class="encyclopedia-card" :class="{ selected: unitKey === unit.key }" :aria-pressed="unitKey === unit.key" :data-unit="unit.key" @click="unitKey = unit.key">
                    <span class="encyclopedia-card-cost">{{ format(unit.recruitment_cost) }}</span>
                    <img v-if="image(unit.icon)" :src="image(unit.icon)" :alt="unit.name" class="encyclopedia-card-image">
                    <span v-else class="encyclopedia-card-fallback" :title="t('encyclopedia.noImage')">{{ unit.name.slice(0, 1) }}</span>
                    <strong>{{ unit.name }}</strong>
                    <span class="encyclopedia-card-category">{{ unit.category || groupLabel(unit.group) }}</span>
                  </button>
                </div>
              </section>
              <p v-if="!visibleUnits.length" class="encyclopedia-empty">{{ t('encyclopedia.empty') }}</p>
            </div>
          </div>
        </div>
        <footer class="encyclopedia-footer">{{ t('encyclopedia.basis') }}</footer>
      </template>
    </section>
  </div>
</template>

<style scoped>
.encyclopedia-backdrop { padding: 0; z-index: 100; background: #080a0b; }
.encyclopedia { width: 100%; height: 100%; display: flex; flex-direction: column; overflow: hidden; color: #e6ddc7; background: #151817; border: 1px solid #8c7347; box-shadow: inset 0 0 0 3px #201f19; outline: none; }
.encyclopedia-detail-title { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 10px; }
.encyclopedia-detail-title h3 { flex: 1; min-width: 0; margin: 0; overflow-wrap: anywhere; }
.encyclopedia-edit { flex: none; padding: 6px 12px; border: 1px solid #8c7045; border-radius: 2px; background: #695034; color: #fff0cc; font-size: 12px !important; box-shadow: inset 0 1px #ffffff18; }
.encyclopedia-edit:hover:not(:disabled) { background: #80613c; border-color: #5c432a; }
.encyclopedia button { font: inherit; cursor: pointer; }
.encyclopedia button:disabled { opacity: .45; cursor: default; }
.encyclopedia button:focus-visible, .encyclopedia input:focus-visible { outline: 2px solid #eac779; outline-offset: 2px; }
.encyclopedia-header { display: flex; align-items: center; gap: 18px; padding: 16px 22px 14px; background: linear-gradient(110deg, #382722, #1b201e 70%); border-bottom: 1px solid #78613e; }
.encyclopedia-heading { margin-right: auto; }
.encyclopedia-kicker { color: #a5967d; font-size: 9px; letter-spacing: 2.2px; }
.encyclopedia-heading h2 { margin: 3px 0 0; color: #eddbab; font: 700 27px Georgia, 'Noto Serif SC', 'Microsoft YaHei', serif; letter-spacing: 3px; }
.encyclopedia-source { color: #c0b397; font-size: 11px; }
.encyclopedia-action { background: #252923; border: 1px solid #7d6a48; border-radius: 2px; color: #e7d6b0; padding: 7px 13px; font-size: 12px !important; }
.encyclopedia-action:hover:not(:disabled) { background: #403b2d; border-color: #c6a567; }
.encyclopedia-close { border: 0; background: none; color: #d3c3a6; font-size: 29px !important; padding: 0 7px; }
.encyclopedia-toolbar { min-height: 56px; padding: 10px 22px; gap: 16px; display: flex; align-items: center; border-bottom: 1px solid #3c3d30; font-size: 12px; color: #aaac9b; }
.encyclopedia-breadcrumb { font-weight: 700; color: #e5d3a8; margin-right: auto; }
.encyclopedia-toolbar input { width: min(320px, 36vw); background: #0e1110; color: #e8dfcd; border: 1px solid #575544; border-radius: 2px; padding: 8px 10px; font: inherit; }
.encyclopedia-factions { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 16px; padding: 24px; overflow-y: auto; align-content: start; flex: 1; }
.encyclopedia-faction { position: relative; min-height: 146px; overflow: hidden; border: 1px solid #756548; background: radial-gradient(ellipse at 65% 20%, #514e36, #1e2521); text-align: left; transition: border-color .15s, transform .15s; }
.encyclopedia-faction:hover { border-color: #e6c377; transform: translateY(-2px); }
.encyclopedia-faction-art { position: absolute; width: 100%; height: 100%; top: 0; right: 0; object-fit: cover; object-position: 100% 50%; }
.encyclopedia-faction-shade { position: absolute; inset: 0; background: linear-gradient(90deg, #151a18f5 3%, #151a1850 75%), linear-gradient(0deg, #0b0e0ddd, transparent 75%); }
.encyclopedia-crest { position: absolute; left: 14px; top: 12px; width: 48px; height: 48px; object-fit: contain; }
.encyclopedia-faction-label { position: absolute; left: 17px; right: 17px; bottom: 15px; color: #fff0ce; text-shadow: 0 2px 5px #000; }
.encyclopedia-faction-label strong { display: block; font-family: Georgia, 'Noto Serif SC', 'Microsoft YaHei', serif; font-size: 19px; margin-bottom: 8px; }
.encyclopedia-faction-label span { display: flex; justify-content: space-between; color: #c6b78f; font-size: 12px; }
.encyclopedia-faction-label b { font-size: 22px; line-height: 12px; }
.encyclopedia-roster { flex: 1; min-height: 0; display: grid; grid-template-columns: 300px minmax(0, 1fr); }
.encyclopedia-detail { overflow-y: auto; background-color: #d6c49c; background-size: 100% 100%; background-repeat: no-repeat; background-blend-mode: screen; color: #32271c; border-right: 3px solid #796448; }
.encyclopedia-portrait { height: 163px; display: flex; align-items: center; justify-content: center; overflow: hidden; background: radial-gradient(ellipse, #655b3d, #252b25); border-bottom: 2px solid #9b8155; }
.encyclopedia-portrait img { width: 100%; height: 100%; object-fit: contain; }
.encyclopedia-portrait-placeholder { font-size: 52px; color: #bfa46c; }
.encyclopedia-detail-copy { padding: 17px 18px; }
.encyclopedia-detail h3 { margin: 0; font: 700 21px/1.3 Georgia, 'Noto Serif SC', 'Microsoft YaHei', serif; }
.encyclopedia-category { display: flex; align-items: center; gap: 6px; color: #5b412c; font-size: 12px; font-weight: 700; }
.encyclopedia-category img { width: 24px; height: 24px; object-fit: contain; }
.encyclopedia-description { margin: 10px 0; font-size: 11px; line-height: 1.7; color: #62513a; font-style: italic; white-space: pre-line; }
.encyclopedia-cost { display: flex; justify-content: space-between; gap: 8px; margin: 12px 0 10px; font-size: 11px; border-top: 1px solid #9179506b; padding-top: 10px; }
.encyclopedia-health { height: 22px; background: linear-gradient(#92b644, #497420 54%, #355019); color: #fff6d7; border: 1px solid #554d23; box-shadow: inset 0 0 0 1px #c2d78769; display: flex; align-items: center; justify-content: center; gap: 5px; font-size: 13px; text-shadow: 0 1px 2px #17270f; }
.encyclopedia-health img { height: 19px; width: 19px; object-fit: contain; }
.encyclopedia-stats { margin: 14px 0 8px; }
.encyclopedia-stat { display: grid; grid-template-columns: minmax(0, 1fr) 42px 44px; align-items: center; gap: 5px; min-height: 26px; font-size: 12px; }
.encyclopedia-stat dt { display: flex; align-items: center; gap: 5px; }
.encyclopedia-stat dt img { width: 22px; height: 22px; object-fit: contain; flex-shrink: 0; }
.encyclopedia-stat dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; }
.encyclopedia-stat-track { display: block; height: 5px; background: #74613e4d; border: 1px solid #877041; }
.encyclopedia-stat-track i { display: block; height: 100%; background: #846326; }
.encyclopedia-damage-breakdown { font-size: 10px; line-height: 1.7; color: #6b5539; border-top: 1px solid #947b5055; padding-top: 6px; }
.encyclopedia-damage-breakdown span { display: block; }
.encyclopedia-resistances { display: flex; flex-wrap: wrap; gap: 5px 12px; margin-top: 12px; font-size: 11px; }
.encyclopedia-detail h4 { margin: 18px 0 8px; font-size: 12px; border-bottom: 1px solid #98805777; padding-bottom: 6px; }
.encyclopedia-features { list-style: none; margin: 0; padding: 0; }
.encyclopedia-features li { display: flex; align-items: center; gap: 8px; min-height: 30px; font-size: 11px; }
.encyclopedia-features img { width: 25px; height: 25px; object-fit: contain; }
.encyclopedia-origin { margin-top: 18px; font-size: 10px; color: #79674d; overflow-wrap: anywhere; }
.encyclopedia-origin summary { cursor: pointer; }
.encyclopedia-origin p { margin: 6px 0; }
.encyclopedia-units-area { min-height: 0; display: flex; flex-direction: column; }
.encyclopedia-units { overflow-y: auto; padding: 18px 20px; flex: 1; }
.encyclopedia-group { margin-bottom: 22px; }
.encyclopedia-group h3 { margin: 0 0 12px; padding: 6px 12px; border: 1px solid #695638; background: linear-gradient(90deg, #552c23, #272923 85%); font: 600 13px Georgia, 'Microsoft YaHei', serif; color: #e1c995; }
.encyclopedia-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(94px, 1fr)); gap: 9px; }
.encyclopedia-card { position: relative; padding: 21px 5px 8px; min-height: 181px; border: 1px solid #5c563d; background: linear-gradient(#2b3028, #1a1e1a); color: #e5ddc4; display: flex; align-items: center; flex-direction: column; gap: 6px; }
.encyclopedia-card:hover { border-color: #c8a667; background: #363829; }
.encyclopedia-card.selected { border-color: #e6c36f; background: linear-gradient(#505039, #2a2e22); box-shadow: inset 0 0 0 1px #aa8744, 0 0 9px #cdb26433; }
.encyclopedia-card-cost { position: absolute; top: 5px; right: 7px; font-size: 10px; color: #cabb87; }
.encyclopedia-card-image { width: 60px; height: 100px; object-fit: contain; filter: drop-shadow(0 2px 3px #0008); }
.encyclopedia-card-fallback { width: 60px; height: 100px; display: grid; place-items: center; color: #8d825b; font: 32px Georgia, serif; background: #151b15; border: 1px solid #615638; }
.encyclopedia-card strong { font-size: 11px; line-height: 1.4; font-weight: 600; overflow-wrap: anywhere; }
.encyclopedia-card-category { font-size: 9px; color: #969a85; margin-top: auto; }
.encyclopedia-roster-tabs { display: flex; gap: 8px; padding: 12px 20px; border-bottom: 1px solid #494634; }
.encyclopedia-roster-tabs button[aria-selected="true"] { background: #55422b; color: #ffe4a6; border-color: #d2af65; }
.encyclopedia-roster-tabs span { margin-left: 8px; opacity: .7; font-variant-numeric: tabular-nums; }
.encyclopedia-footer { padding: 9px 22px; border-top: 1px solid #494634; color: #9b9d8d; font-size: 10px; }
.encyclopedia-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; font-size: 14px; padding: 32px; }
.encyclopedia-empty { padding: 40px 12px; font-size: 13px; text-align: center; color: #a3a087; }
.encyclopedia-image-warning { padding: 5px 22px; font-size: 11px; color: #d4bd84; }
@media (max-width: 1000px) {
  .encyclopedia-roster { grid-template-columns: 266px minmax(0, 1fr); }
  .encyclopedia-source { display: none; }
  .encyclopedia-units { padding: 14px 12px; }
  .encyclopedia-factions { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
}
@media (max-width: 640px) {
  .encyclopedia-header { padding: 10px; gap: 10px; }
  .encyclopedia-heading h2 { font-size: 21px; }
  .encyclopedia-kicker { font-size: 7px; }
  .encyclopedia-toolbar { flex-wrap: wrap; gap: 8px; padding: 8px 10px; }
  .encyclopedia-toolbar input { width: 100%; order: 3; }
  .encyclopedia-roster { grid-template-columns: 210px minmax(0, 1fr); }
  .encyclopedia-detail-copy { padding: 12px 9px; }
  .encyclopedia-stat { grid-template-columns: minmax(0, 1fr) 36px; }
  .encyclopedia-stat-track { display: none; }
  .encyclopedia-cards { grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); }
  .encyclopedia-factions { padding: 14px; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
}
</style>
