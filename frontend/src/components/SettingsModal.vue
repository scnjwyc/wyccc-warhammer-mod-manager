<script setup>
import { reactive, ref, watch } from 'vue'
import aboutLogoUrl from '../assets/icon.svg'
import donationQrUrl from '../assets/donate-qr.jpg'
import {
  DEFAULT_LANGUAGE,
  LANGUAGE_OPTIONS,
  applyInterfaceLanguage,
  languageLabel,
  t,
} from '../languages'
import { useAppStore } from '../store'

const props = defineProps({
  open: { type: Boolean, default: false },
  settings: { type: Object, default: () => ({}) },
  health: { type: Object, default: () => ({}) },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'save', 'detect', 'check-update', 'show-changelog'])
const store = useAppStore()
const draft = reactive({})
const activeTab = ref('basic')
const donationOpen = ref(false)

const tabs = [
  { id: 'basic', labelKey: 'settings.tabBasic', detailKey: 'settings.tabBasicDetail', marker: '01' },
  { id: 'features', labelKey: 'settings.tabFeatures', detailKey: 'settings.tabFeaturesDetail', marker: '02' },
  { id: 'ai', labelKey: 'settings.tabAi', detailKey: 'settings.tabAiDetail', marker: 'AI' },
  { id: 'about', labelKey: 'settings.tabAbout', detailKey: 'settings.tabAboutDetail', marker: '04' },
]

const downloadLinks = [
  {
    labelKey: 'settings.githubReleases',
    url: 'https://github.com/scnjwyc/wyccc-warhammer-mod-manager/releases',
    noteKey: 'settings.githubReleasesNote',
  },
  {
    labelKey: 'settings.giteeReleases',
    url: 'https://gitee.com/wyccc2018/wyccc-warhammer-mod-manager/releases',
    noteKey: 'settings.giteeReleasesNote',
  },
]

const feedbackLinks = [
  {
    label: 'GitHub Issues',
    url: 'https://github.com/scnjwyc/wyccc-warhammer-mod-manager/issues',
    noteKey: 'settings.githubIssuesNote',
  },
  {
    labelKey: 'settings.qqGroup',
    value: '592799189',
    noteKey: 'settings.qqGroupNote',
  },
]

watch(
  () => [props.open, props.settings],
  () => {
    Object.keys(draft).forEach(key => delete draft[key])
    Object.assign(draft, props.settings)
    if (!draft.language) draft.language = DEFAULT_LANGUAGE
    draft.clear_ai_api_key = false
  },
  { immediate: true, deep: true },
)

watch(
  () => props.open,
  open => {
    if (open) activeTab.value = 'basic'
    else donationOpen.value = false
  },
)

const browse = async kind => {
  const result = await store.selectDirectory(kind)
  if (!result.path) return
  if (kind === 'game') draft.game_path = result.path
  else draft.workshop_path = result.path
}

const openExternalUrl = async url => {
  try {
    await store.openExternalUrl(url)
  } catch (error) {
    store.notify(error.message || t('settings.openFailed'), 'error')
  }
}

const copyText = async value => {
  try {
    await navigator.clipboard.writeText(value)
    store.notify(t('settings.linkCopied'))
  } catch {
    store.notify(t('settings.copyFailed'), 'error')
  }
}

const previewLanguage = () => applyInterfaceLanguage(draft.language)

const closeSettings = () => {
  applyInterfaceLanguage(props.settings.language || DEFAULT_LANGUAGE)
  emit('close')
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="closeSettings">
    <section class="modal-card settings-modal" role="dialog" aria-modal="true" :aria-label="t('settings.aria')">
      <header class="modal-header">
        <div>
          <span class="eyebrow">{{ t('settings.eyebrow') }}</span>
          <h2>{{ t('settings.title') }}</h2>
        </div>
        <button type="button" class="icon-button" @click="closeSettings">×</button>
      </header>

      <div class="modal-body settings-layout">
        <nav class="settings-tabs" :aria-label="t('settings.pagesAria')">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            type="button"
            class="settings-tab-button"
            :class="{ active: activeTab === tab.id }"
            :data-testid="`settings-tab-${tab.id}`"
            @click="activeTab = tab.id"
          >
            <span class="settings-tab-marker">{{ tab.marker }}</span>
            <span class="settings-tab-copy">
              <strong>{{ t(tab.labelKey) }}</strong>
              <small>{{ t(tab.detailKey) }}</small>
            </span>
          </button>
        </nav>

        <div class="settings-page-scroll">
          <section v-show="activeTab === 'basic'" class="settings-page" data-testid="settings-page-basic">
            <div class="settings-page-heading">
              <span class="eyebrow">{{ t('settings.basicEyebrow') }}</span>
              <h3>{{ t('settings.tabBasic') }}</h3>
              <p>{{ t('settings.basicIntro') }}</p>
            </div>

            <div class="health-card" :class="{ healthy: health.game_ready }">
              <span class="health-dot"></span>
              <div>
                <strong>{{ health.game_ready ? t('settings.pathValid') : t('settings.pathInvalid') }}</strong>
                <p>{{ t('settings.pathRequirement') }}</p>
              </div>
              <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('detect')">
                {{ t('settings.autoDetectSteam') }}
              </button>
            </div>

            <label class="field-label language-field">
              <span>{{ t('settings.interfaceLanguage') }}</span>
              <select v-model="draft.language" data-testid="language-select" @change="previewLanguage">
                <option v-for="language in LANGUAGE_OPTIONS" :key="language.code" :value="language.code">
                  {{ languageLabel(language) }}
                </option>
              </select>
              <small class="field-help">{{ t('settings.languageHelp') }}</small>
            </label>

            <label class="field-label">
              <span>{{ t('settings.gameFolder') }}</span>
              <div class="path-input-row">
                <input v-model="draft.game_path" type="text" placeholder="...\steamapps\common\Total War WARHAMMER III" />
                <button type="button" class="secondary-button" @click="browse('game')">{{ t('common.browse') }}</button>
              </div>
            </label>

            <label class="field-label">
              <span>{{ t('settings.workshopFolder') }}</span>
              <div class="path-input-row">
                <input v-model="draft.workshop_path" type="text" placeholder="...\workshop\content\1142710" />
                <button type="button" class="secondary-button" @click="browse('workshop')">{{ t('common.browse') }}</button>
              </div>
            </label>

            <div class="settings-section">
              <h3>{{ t('settings.workshopChecks') }}</h3>
              <p class="settings-scan-note">{{ t('settings.scanScope') }}</p>
              <label class="switch-row">
                <input v-model="draft.fetch_workshop_metadata" type="checkbox" />
                <span><strong>{{ t('settings.refreshOnStart') }}</strong><small>{{ t('settings.refreshOnStartHelp') }}</small></span>
              </label>
              <label class="switch-row">
                <input v-model="draft.live_mod_detection" type="checkbox" data-testid="live-mod-detection" />
                <span><strong>{{ t('settings.liveModDetection') }}</strong><small>{{ t('settings.liveModDetectionHelp') }}</small></span>
              </label>
              <label class="switch-row">
                <input v-model="draft.check_outdated_mods" type="checkbox" data-testid="check-outdated-mods" />
                <span><strong>{{ t('settings.checkOutdated') }}</strong><small>{{ t('settings.checkOutdatedHelp') }}</small></span>
              </label>
            </div>
          </section>

          <section v-show="activeTab === 'features'" class="settings-page" data-testid="settings-page-features">
            <div class="settings-page-heading">
              <span class="eyebrow">{{ t('settings.featuresEyebrow') }}</span>
              <h3>{{ t('settings.tabFeaturesDetail') }}</h3>
              <p>{{ t('settings.featuresIntro') }}</p>
            </div>

            <div class="settings-feature-card">
              <label class="switch-row">
                <input v-model="draft.custom_battle_all_units_as_lords" type="checkbox" data-testid="all-units-as-lords" />
                <span><strong>{{ t('settings.allUnitsLords') }}</strong><small>{{ t('settings.allUnitsLordsHelp') }}</small></span>
              </label>
              <label class="switch-row">
                <input v-model="draft.enable_script_logging" type="checkbox" data-testid="script-logging" />
                <span><strong>{{ t('settings.scriptLogging') }}</strong><small>{{ t('settings.scriptLoggingHelp') }}</small></span>
              </label>
              <label class="switch-row">
                <input v-model="draft.skip_intro_movies" type="checkbox" data-testid="skip-intro-movies" />
                <span><strong>{{ t('settings.skipIntro') }}</strong><small>{{ t('settings.skipIntroHelp') }}</small></span>
              </label>
            </div>
            <p class="settings-page-note">{{ t('settings.runtimeNote') }}</p>
          </section>

          <section v-show="activeTab === 'ai'" class="settings-page" data-testid="settings-page-ai">
            <div class="settings-page-heading">
              <span class="eyebrow">{{ t('settings.aiEyebrow') }}</span>
              <h3>{{ t('settings.tabAi') }}</h3>
              <p>{{ t('settings.aiIntro') }}</p>
            </div>

            <div class="settings-feature-card">
              <label class="switch-row">
                <input v-model="draft.ai_enabled" type="checkbox" data-testid="ai-enabled" />
                <span><strong>{{ t('settings.aiEnable') }}</strong><small>{{ t('settings.aiEnableHelp') }}</small></span>
              </label>
              <div class="settings-field-grid" :class="{ disabled: !draft.ai_enabled }">
                <label class="field-label settings-wide-field">
                  <span>{{ t('settings.baseUrl') }}</span>
                  <input v-model="draft.ai_base_url" type="url" data-testid="ai-base-url" placeholder="https://api.openai.com/v1" />
                </label>
                <label class="field-label">
                  <span>{{ t('settings.model') }}</span>
                  <input v-model="draft.ai_model" type="text" data-testid="ai-model" :placeholder="t('settings.modelPlaceholder')" />
                </label>
                <label class="field-label">
                  <span>{{ t('settings.temperature') }}</span>
                  <input v-model.number="draft.ai_temperature" type="number" min="0" max="2" step="0.1" data-testid="ai-temperature" />
                </label>
                <label class="field-label settings-wide-field">
                  <span>{{ t('settings.apiKey') }}</span>
                  <input
                    v-model="draft.ai_api_key"
                    type="password"
                    data-testid="ai-api-key"
                    :placeholder="draft.ai_api_key_configured ? t('settings.secretSaved') : t('settings.secretOptional')"
                    autocomplete="new-password"
                  />
                </label>
                <label v-if="draft.ai_api_key_configured" class="clear-secret-row settings-wide-field">
                  <input v-model="draft.clear_ai_api_key" type="checkbox" />
                  {{ t('settings.clearSecret') }}
                </label>
              </div>
            </div>
            <p class="settings-page-note">{{ t('settings.aiNote') }}</p>
          </section>

          <section v-show="activeTab === 'about'" class="settings-page settings-about-page" data-testid="settings-page-about">
            <div class="about-project-hero">
              <img :src="aboutLogoUrl" alt="Wyccc's Mod Manager" class="about-project-logo" />
              <div class="about-project-copy">
                <div class="about-project-title-row">
                  <h3>{{ store.appName }}</h3>
                  <span>v{{ store.appVersion }}</span>
                </div>
                <p>{{ t('settings.aboutIntro') }}</p>
              </div>
              <div class="about-update-actions">
                <label class="about-auto-update">
                  <input v-model="draft.check_updates_automatically" type="checkbox" data-testid="auto-update-check" />
                  <span><strong>{{ t('settings.autoUpdate') }}</strong><small>{{ t('settings.autoUpdateHelp') }}</small></span>
                </label>
                <div>
                  <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('show-changelog')">{{ t('update.changelog') }}</button>
                  <button
                    type="button"
                    class="secondary-button update-check-button"
                    :disabled="!!busy"
                    @click="emit('check-update', String(draft.update_manifest_url || '').trim())"
                  >
                    {{ busy === t('busy.checkUpdates') ? busy : t('settings.checkUpdate') }}
                  </button>
                </div>
              </div>
            </div>

            <div class="about-grid">
              <article class="about-card">
                <header><h4>{{ t('settings.downloads') }}</h4><p>{{ t('settings.downloadsHelp') }}</p></header>
                <div class="about-link-list">
                  <div v-for="item in downloadLinks" :key="item.url" class="about-link-row">
                    <div><strong>{{ t(item.labelKey) }}</strong><code>{{ item.url }}</code><small>{{ t(item.noteKey) }}</small></div>
                    <span>
                      <button type="button" class="about-link-button" :title="t('common.openLink')" @click="openExternalUrl(item.url)">↗</button>
                      <button type="button" class="about-link-button" :title="t('common.copyLink')" @click="copyText(item.url)">⧉</button>
                    </span>
                  </div>
                </div>
              </article>

              <article class="about-card">
                <header><h4>{{ t('settings.feedback') }}</h4><p>{{ t('settings.feedbackHelp') }}</p></header>
                <div class="about-link-list">
                  <div
                    v-for="item in feedbackLinks"
                    :key="item.url || item.value"
                    class="about-link-row"
                    :data-testid="item.value ? 'feedback-qq-group' : undefined"
                  >
                    <div><strong>{{ item.labelKey ? t(item.labelKey) : item.label }}</strong><code>{{ item.url || item.value }}</code><small>{{ t(item.noteKey) }}</small></div>
                    <span>
                      <button v-if="item.url" type="button" class="about-link-button" :title="t('common.openLink')" @click="openExternalUrl(item.url)">↗</button>
                      <button
                        type="button"
                        class="about-link-button"
                        :title="item.url ? t('common.copyLink') : t('common.copyGroup')"
                        @click="copyText(item.url || item.value)"
                      >⧉</button>
                    </span>
                  </div>
                </div>
              </article>

              <article class="about-card about-wide-card software-update-settings">
                <header><h4>{{ t('settings.updateChannel') }}</h4><p>{{ t('settings.updateChannelHelp') }}</p></header>
                <label class="field-label update-manifest-field">
                  <span>{{ t('settings.customManifest') }}</span>
                  <input
                    v-model="draft.update_manifest_url"
                    type="url"
                    data-testid="update-manifest-url"
                    :placeholder="t('settings.manifestPlaceholder')"
                  />
                  <small class="field-help">{{ t('settings.manifestHelp') }}</small>
                </label>
              </article>

              <article class="about-card about-wide-card donation-card">
                <div>
                  <span class="donation-heart">♥</span>
                  <div><h4>{{ t('settings.donate') }}</h4><p>{{ t('settings.donateHelp') }}</p></div>
                </div>
                <button type="button" class="secondary-button" @click="donationOpen = true">{{ t('settings.showQr') }}</button>
              </article>
            </div>
          </section>
        </div>
      </div>

      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="closeSettings">{{ t('common.cancel') }}</button>
        <button type="button" class="primary-button" :disabled="!!busy" @click="emit('save', { ...draft })">
          {{ t('settings.saveRescan') }}
        </button>
      </footer>
    </section>
  </div>

  <Teleport to="body">
    <div v-if="open && donationOpen" class="modal-backdrop donation-backdrop" @mousedown.self="donationOpen = false">
      <section class="modal-card donation-modal" role="dialog" aria-modal="true" :aria-label="t('settings.donate')">
        <header class="modal-header">
          <div><span class="eyebrow">{{ t('settings.donateEyebrow') }}</span><h2>{{ t('settings.donate') }}</h2></div>
          <button type="button" class="icon-button" @click="donationOpen = false">×</button>
        </header>
        <div class="modal-body donation-modal-body">
          <img :src="donationQrUrl" :alt="t('settings.donateAlt')" />
          <p>{{ t('settings.donateThanks') }}</p>
        </div>
      </section>
    </div>
  </Teleport>
</template>
