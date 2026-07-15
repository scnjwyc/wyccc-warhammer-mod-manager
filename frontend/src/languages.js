export const DEFAULT_LANGUAGE = 'zh-CN'

export const LANGUAGE_OPTIONS = Object.freeze([
  { code: 'zh-CN', label: '中文' },
  { code: 'en-US', label: 'English' },
  { code: 'ko-KR', label: '한국어' },
  { code: 'ru-RU', label: 'Русский' },
  { code: 'ja-JP', label: '日本語' },
])

const supportedLanguages = new Set(LANGUAGE_OPTIONS.map(language => language.code))

// All selectable languages intentionally use the Chinese catalog until the UI is final.
const contentLanguageBySelection = Object.freeze(
  Object.fromEntries(LANGUAGE_OPTIONS.map(language => [language.code, DEFAULT_LANGUAGE])),
)

export const normalizeLanguage = language => (
  supportedLanguages.has(language) ? language : DEFAULT_LANGUAGE
)

export const contentLanguageFor = language => (
  contentLanguageBySelection[normalizeLanguage(language)] || DEFAULT_LANGUAGE
)

export const applyInterfaceLanguage = language => {
  const selectedLanguage = normalizeLanguage(language)
  const contentLanguage = contentLanguageFor(selectedLanguage)
  document.documentElement.lang = contentLanguage
  document.documentElement.dataset.selectedLanguage = selectedLanguage
  document.documentElement.dataset.contentLanguage = contentLanguage
  return selectedLanguage
}
