<script setup>
import { computed, ref, watch } from 'vue'

import { currentLocale, t } from '../languages'
import { renderWorkshopBbcode } from '../workshopBbcode'

const props = defineProps({
  mod: { type: Object, default: null },
  preview: { type: String, default: '' },
  aiEnabled: { type: Boolean, default: false },
  generateUserData: { type: Function, default: null },
})

const emit = defineEmits(['save-user-data', 'open-folder', 'open-workshop-folder', 'open-workshop'])
const alias = ref('')
const notes = ref('')
const aiGenerating = ref(false)
const renderedDescription = computed(() => renderWorkshopBbcode(props.mod?.description || ''))

watch(
  () => props.mod,
  mod => {
    alias.value = mod?.alias || ''
    notes.value = mod?.notes || ''
  },
  { immediate: true },
)

const sourceLabel = source => ({
  workshop: t('details.sourceWorkshop'),
  data: t('details.sourceData'),
}[source] || source)

const formatDate = value => {
  if (!value) return '—'
  return new Intl.DateTimeFormat(currentLocale(), {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

const formatAuthor = mod => {
  if (mod.author) return mod.author
  if (mod.creator_id) return t('details.authorUnavailable')
  if (mod.workshop_id) return t('details.authorRefreshing')
  return t('common.unknown')
}

const formatSources = mod => (mod.sources?.length ? mod.sources : [mod.source])
  .map(sourceLabel)
  .join(' + ')

const generateWithAi = async () => {
  if (!props.mod || !props.generateUserData || !props.aiEnabled || aiGenerating.value) return
  const requestedId = props.mod.id
  aiGenerating.value = true
  try {
    const updated = await props.generateUserData(requestedId)
    if (props.mod?.id === requestedId && updated) {
      alias.value = updated.alias || ''
      notes.value = updated.notes || ''
    }
  } catch {
    // The shared store toast contains the user-facing error.
  } finally {
    aiGenerating.value = false
  }
}
</script>

<template>
  <aside class="details-panel" data-testid="mod-details">
    <template v-if="mod">
      <div class="details-visual">
        <img v-if="preview" :src="preview" :alt="mod.effective_name" />
        <div v-else class="details-placeholder">
          <span>{{ mod.effective_name.slice(0, 1).toUpperCase() }}</span>
        </div>
        <div class="details-gradient"></div>
        <div class="details-title">
          <span class="eyebrow">{{ formatSources(mod) }}</span>
          <h1>{{ mod.effective_name }}</h1>
          <p
            class="details-source-name"
            :class="{ 'has-original-name': mod.alias && mod.display_name }"
            :title="mod.alias && mod.display_name
              ? `${mod.pack_name} · ${t('common.originalName', { name: mod.display_name })}`
              : mod.pack_name"
            data-testid="mod-source-name"
          >
            <span>{{ mod.pack_name }}</span>
            <span v-if="mod.alias && mod.display_name" class="original-mod-name">
              · {{ t('common.originalName', { name: mod.display_name }) }}
            </span>
          </p>
          <dl class="details-meta" :aria-label="t('details.basicInfo')">
            <div v-if="mod.workshop_id">
              <dt>{{ t('details.workshopId') }}</dt>
              <dd :title="mod.workshop_id">{{ mod.workshop_id }}</dd>
            </div>
            <div>
              <dt>{{ t('details.author') }}</dt>
              <dd :title="mod.creator_id ? `${formatAuthor(mod)} · Steam ID ${mod.creator_id}` : formatAuthor(mod)">
                {{ formatAuthor(mod) }}
              </dd>
            </div>
            <div>
              <dt>{{ t('details.createdAt') }}</dt>
              <dd>{{ formatDate(mod.created_at) }}</dd>
            </div>
            <div>
              <dt>{{ t('details.updatedAt') }}</dt>
              <dd>{{ formatDate(mod.updated_at) }}</dd>
            </div>
          </dl>
        </div>
      </div>

      <div class="details-scroll">
        <section class="detail-section">
          <h3>{{ t('details.localLocation') }}</h3>
          <p class="path-value" :title="mod.path">{{ mod.path }}</p>
          <div class="button-row">
            <button type="button" class="secondary-button sync-data-button" @click="emit('open-folder', mod.id)">
              {{ t('details.openFolder') }}
            </button>
            <button
              v-if="mod.cross_source_duplicate && mod.workshop_id"
              type="button"
              class="secondary-button sync-data-button"
              @click="emit('open-workshop-folder', mod.id)"
            >
              {{ t('details.openWorkshopFolder') }}
            </button>
            <button
              v-if="mod.workshop_id"
              type="button"
              class="secondary-button sync-data-button"
              @click="emit('open-workshop', mod.id)"
            >
              {{ t('details.workshopPage') }}
            </button>
          </div>
        </section>

        <section v-if="mod.description" class="detail-section">
          <h3>{{ t('details.description') }}</h3>
          <div
            class="description-text workshop-bbcode"
            data-testid="workshop-description"
            v-html="renderedDescription"
          ></div>
        </section>

        <section class="detail-section">
          <h3>{{ t('details.myMarks') }}</h3>
          <label class="field-label">
            <span class="field-label-heading">
              <span>{{ t('details.alias') }}</span>
              <button
                type="button"
                class="ai-generate-button"
                :disabled="!aiEnabled || aiGenerating"
                :title="aiEnabled ? t('details.aiEnabledTitle') : t('details.aiDisabledTitle')"
                data-testid="ai-generate-user-data"
                @click.prevent="generateWithAi"
              >
                <span v-if="aiGenerating" class="spinner"></span>
                {{ aiGenerating ? t('details.generating') : t('details.aiGenerate') }}
              </button>
            </span>
            <input v-model="alias" type="text" maxlength="120" :placeholder="t('details.aliasPlaceholder')" />
          </label>
          <label class="field-label">
            <span>{{ t('details.notes') }}</span>
            <textarea v-model="notes" rows="4" maxlength="2000" :placeholder="t('details.notesPlaceholder')"></textarea>
          </label>
          <button
            type="button"
            class="primary-button compact"
            @click="emit('save-user-data', mod.id, alias, notes)"
          >
            {{ t('details.saveMarks') }}
          </button>
        </section>
      </div>
    </template>

    <div v-else class="details-empty">
      <span class="crest">W</span>
      <h2>{{ t('details.selectMod') }}</h2>
      <p>{{ t('details.emptyHelp') }}</p>
    </div>
  </aside>
</template>
