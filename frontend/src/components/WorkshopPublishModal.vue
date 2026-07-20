<script setup>
import { computed, reactive, ref, watch } from 'vue'

import { LANGUAGE_OPTIONS, languageLabel, normalizeLanguage, t } from '../languages'
import { useAppStore } from '../store'
import ThemedSelect from './ThemedSelect.vue'

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
  category: 'graphical',
  visibility: 0,
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
const languageSelectOptions = computed(() => LANGUAGE_OPTIONS.map(language => ({
  value: language.code,
  label: languageLabel(language),
})))
const categorySelectOptions = computed(() => categories.map(category => ({
  value: category[0],
  label: t(category[1]),
})))
const visibilitySelectOptions = computed(() => [
  { value: 0, label: t('publish.public') },
  { value: 1, label: t('publish.friendsOnly') },
  { value: 2, label: t('publish.private') },
  { value: 3, label: t('publish.unlisted') },
])

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
    draft.category = 'graphical'
    draft.visibility = 0
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

const submit = () => {
  if (!draft.title.trim()) return
  emit('submit', {
    mode: props.mode,
    title: draft.title.trim(),
    description: draft.description,
    change_note: draft.change_note,
    language: draft.language,
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
        <button type="button" class="icon-button" :disabled="!!busy" @click="emit('close')">×</button>
      </header>

      <div class="modal-body publish-form">
        <p class="publish-pack-path" :title="mod.path">{{ mod.pack_name }} · {{ mod.path }}</p>
        <label v-if="mode === 'update'" class="field-label">
          <span>{{ t('publish.workshopId') }}</span>
          <input :value="mod.workshop_id" type="text" readonly />
        </label>
        <div v-if="mode === 'update'" class="field-label publish-language-field">
          <span>{{ t('publish.language') }}</span>
          <ThemedSelect
            v-model="draft.language"
            :options="languageSelectOptions"
            :aria-label="t('publish.language')"
            data-testid="publish-language-select"
            :disabled="!!busy || languageLoading"
            @change="loadWorkshopLanguage(draft.language)"
          />
          <small class="field-help">{{ t('publish.languageHelp') }}</small>
          <small v-if="languageMessage" class="publish-language-status">{{ languageMessage }}</small>
        </div>
        <label class="field-label">
          <span>{{ t('publish.title') }}</span>
          <input v-model="draft.title" type="text" maxlength="128" :disabled="languageLoading" />
        </label>
        <label class="field-label">
          <span>{{ t('publish.description') }}</span>
          <textarea
            v-model="draft.description"
            class="publish-textarea"
            rows="6"
            maxlength="8000"
            :disabled="languageLoading"
          ></textarea>
        </label>
        <label v-if="mode === 'update'" class="field-label">
          <span>{{ t('publish.changelog') }}</span>
          <textarea v-model="draft.change_note" class="publish-textarea" rows="3" maxlength="8000"></textarea>
        </label>
        <div class="publish-grid">
          <div class="field-label">
            <span>{{ t('publish.category') }}</span>
            <ThemedSelect
              v-model="draft.category"
              :options="categorySelectOptions"
              :aria-label="t('publish.category')"
              data-testid="publish-category-select"
            />
          </div>
          <div class="field-label">
            <span>{{ t('publish.visibility') }}</span>
            <ThemedSelect
              v-model="draft.visibility"
              :options="visibilitySelectOptions"
              :aria-label="t('publish.visibility')"
              data-testid="publish-visibility-select"
            />
          </div>
        </div>
      </div>

      <footer class="modal-footer">
        <span class="publish-warning">{{ t('publish.keepSteamOnline') }}</span>
        <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('close')">{{ t('common.cancel') }}</button>
        <button
          type="button"
          class="primary-button"
          :disabled="!!busy || languageLoading || !draft.title.trim()"
          @click="submit"
        >
          {{ busy || (mode === 'upload' ? t('publish.createUpload') : t('publish.submitUpdate')) }}
        </button>
      </footer>
    </section>
  </div>
</template>
