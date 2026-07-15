<script setup>
import { reactive, ref, watch } from 'vue'

import { LANGUAGE_OPTIONS, languageLabel, normalizeLanguage, t } from '../languages'
import { useAppStore } from '../store'

const props = defineProps({
  open: { type: Boolean, default: false },
  mode: { type: String, default: 'upload' },
  mod: { type: Object, default: null },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'submit'])
const store = useAppStore()
const draft = reactive({
  title: '',
  description: '',
  change_note: '',
  language: 'en-US',
  preview_path: '',
  category: 'graphical',
  visibility: 0,
  confirmed: false,
})
const languageLoading = ref(false)
const languageMessage = ref('')
let languageRequestId = 0

const categories = [
  ['graphical', 'publish.categoryGraphical'],
  ['campaign', 'publish.categoryCampaign'],
  ['units', 'publish.categoryUnits'],
  ['battle', 'publish.categoryBattle'],
  ['ui', 'publish.categoryUi'],
  ['maps', 'publish.categoryMaps'],
  ['overhaul', 'publish.categoryOverhaul'],
  ['compilation', 'publish.categoryCompilation'],
  ['cheat', 'publish.categoryCheat'],
]

watch(
  () => [props.open, props.mod?.id, props.mode],
  () => {
    if (!props.open || !props.mod) return
    draft.title = props.mod.effective_name || props.mod.display_name || props.mod.pack_name || ''
    draft.description = props.mod.description || ''
    draft.change_note = ''
    draft.language = props.mode === 'update'
      ? normalizeLanguage(store.settings.language)
      : 'en-US'
    draft.preview_path = props.mod.preview_path || ''
    draft.category = 'graphical'
    draft.visibility = 0
    draft.confirmed = false
    languageMessage.value = ''
    languageRequestId += 1
    if (props.mode === 'update' && props.mod.workshop_id) {
      void loadWorkshopLanguage(draft.language, true)
    }
  },
  { immediate: true },
)

async function loadWorkshopLanguage(language, allowEnglishDefault = false) {
  if (props.mode !== 'update' || !props.mod?.workshop_id) return
  const requestedLanguage = normalizeLanguage(language)
  const requestId = ++languageRequestId
  languageLoading.value = true
  languageMessage.value = t('publish.loadingLanguage')
  try {
    const data = await store.loadWorkshopPublishCopy(props.mod.id, requestedLanguage)
    if (requestId !== languageRequestId) return
    draft.title = data.title || ''
    draft.description = data.description || ''
    if (allowEnglishDefault && data.suggested_language === 'en-US' && requestedLanguage !== 'en-US') {
      const englishData = await store.loadWorkshopPublishCopy(props.mod.id, 'en-US')
      if (requestId !== languageRequestId) return
      draft.language = 'en-US'
      draft.title = englishData.title || ''
      draft.description = englishData.description || ''
      languageMessage.value = t('publish.fallbackEnglish')
    } else if (data.effective_language !== requestedLanguage) {
      languageMessage.value = t('publish.partialEnglish')
    } else {
      languageMessage.value = t('publish.loadedLanguage')
    }
  } catch {
    if (requestId === languageRequestId) {
      languageMessage.value = t('publish.loadFailed')
    }
  } finally {
    if (requestId === languageRequestId) languageLoading.value = false
  }
}

const browsePreview = async () => {
  const result = await store.selectDirectory('preview')
  if (result.path) draft.preview_path = result.path
}

const submit = () => {
  if (!draft.confirmed || !draft.title.trim() || !draft.preview_path.trim()) return
  emit('submit', {
    mode: props.mode,
    title: draft.title.trim(),
    description: draft.description,
    change_note: draft.change_note,
    language: draft.language,
    preview_path: draft.preview_path.trim(),
    category: draft.category,
    visibility: Number(draft.visibility),
  })
}
</script>

<template>
  <div v-if="open && mod" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card workshop-publish-modal" role="dialog" aria-modal="true" :aria-label="t('publish.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('publish.eyebrow') }}</span>
          <h2>{{ mode === 'upload' ? t('publish.upload') : t('publish.update') }}</h2>
        </div>
        <button type="button" class="close-button" :disabled="!!busy" @click="emit('close')">×</button>
      </header>

      <div class="modal-body publish-form">
        <p class="publish-pack-path" :title="mod.path">{{ mod.pack_name }} · {{ mod.path }}</p>
        <label v-if="mode === 'update'" class="field-label">
          <span>{{ t('publish.workshopId') }}</span>
          <input :value="mod.workshop_id" type="text" readonly />
        </label>
        <label v-if="mode === 'update'" class="field-label publish-language-field">
          <span>{{ t('publish.language') }}</span>
          <select
            v-model="draft.language"
            data-testid="publish-language-select"
            :disabled="!!busy || languageLoading"
            @change="loadWorkshopLanguage(draft.language)"
          >
            <option v-for="language in LANGUAGE_OPTIONS" :key="language.code" :value="language.code">
              {{ languageLabel(language) }}
            </option>
          </select>
          <small class="field-help">{{ t('publish.languageHelp') }}</small>
          <small v-if="languageMessage" class="publish-language-status">{{ languageMessage }}</small>
        </label>
        <label class="field-label">
          <span>{{ t('publish.title') }}</span>
          <input v-model="draft.title" type="text" maxlength="128" :disabled="languageLoading" />
        </label>
        <label class="field-label">
          <span>{{ t('publish.description') }}</span>
          <textarea v-model="draft.description" rows="6" maxlength="8000" :disabled="languageLoading"></textarea>
        </label>
        <label v-if="mode === 'update'" class="field-label">
          <span>{{ t('publish.changelog') }}</span>
          <textarea v-model="draft.change_note" rows="3" maxlength="8000"></textarea>
        </label>
        <label class="field-label">
          <span>{{ t('publish.preview') }}</span>
          <div class="path-input-row">
            <input v-model="draft.preview_path" type="text" />
            <button type="button" class="secondary-button" @click="browsePreview">{{ t('common.browse') }}</button>
          </div>
        </label>
        <div class="publish-grid">
          <label class="field-label">
            <span>{{ t('publish.category') }}</span>
            <select v-model="draft.category">
              <option v-for="category in categories" :key="category[0]" :value="category[0]">{{ t(category[1]) }}</option>
            </select>
          </label>
          <label class="field-label">
            <span>{{ t('publish.visibility') }}</span>
            <select v-model="draft.visibility">
              <option :value="0">{{ t('publish.public') }}</option>
              <option :value="1">{{ t('publish.friendsOnly') }}</option>
              <option :value="2">{{ t('publish.private') }}</option>
              <option :value="3">{{ t('publish.unlisted') }}</option>
            </select>
          </label>
        </div>
        <label class="publish-confirmation">
          <input v-model="draft.confirmed" type="checkbox" />
          <span>
            {{ mode === 'upload'
              ? t('publish.confirmUpload')
              : t('publish.confirmUpdate') }}
          </span>
        </label>
      </div>

      <footer class="modal-footer">
        <span class="publish-warning">{{ t('publish.keepSteamOnline') }}</span>
        <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">{{ t('common.cancel') }}</button>
        <button
          type="button"
          class="primary-button"
          :disabled="!!busy || !draft.confirmed || !draft.title.trim() || !draft.preview_path.trim()"
          @click="submit"
        >
          {{ busy || (mode === 'upload' ? t('publish.createUpload') : t('publish.submitUpdate')) }}
        </button>
      </footer>
    </section>
  </div>
</template>
