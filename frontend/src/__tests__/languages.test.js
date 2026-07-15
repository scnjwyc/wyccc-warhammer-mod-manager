// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_LANGUAGE,
  applyInterfaceLanguage,
  hasTranslation,
  localizeBackendMessage,
  t,
  translationKeys,
} from '../languages'

afterEach(() => applyInterfaceLanguage('zh-CN'))

describe('built-in interface languages', () => {
  it('uses English when no detected or stored interface language is available', () => {
    expect(DEFAULT_LANGUAGE).toBe('en-US')
    applyInterfaceLanguage('unsupported')
    expect(t('update.changelog')).toBe('Changelog')
  })

  it('provides all five variants for every UI translation key', () => {
    expect(translationKeys.length).toBeGreaterThan(250)
    expect(translationKeys.every(hasTranslation)).toBe(true)
  })

  it('switches visible text instead of only changing the document language', () => {
    const labels = new Map()
    for (const language of ['zh-CN', 'en-US', 'ko-KR', 'ru-RU', 'ja-JP']) {
      applyInterfaceLanguage(language)
      labels.set(language, t('update.changelog'))
      expect(document.documentElement.lang).toBe(language)
      expect(t('app.activeMods')).not.toBe('app.activeMods')
    }
    expect(new Set(labels.values()).size).toBe(5)
  })

  it('does not leak Chinese backend warnings into another selected language', () => {
    applyInterfaceLanguage('en-US')
    const message = localizeBackendMessage('缺少依赖：base.pack')
    expect(message).toBe('Missing dependencies: base.pack')
    expect(message).not.toMatch(/[\u3400-\u9fff]/u)
  })

  it('keeps each static interface catalog free of unrelated writing systems', () => {
    const forbiddenByLanguage = {
      'zh-CN': /[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]/u,
      'en-US': /[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]/u,
      'ko-KR': /[\u3400-\u9fff\u3040-\u30ff\u0400-\u04ff]/u,
      'ru-RU': /[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]/u,
      'ja-JP': /[\uac00-\ud7af\u0400-\u04ff]/u,
    }

    for (const [language, forbidden] of Object.entries(forbiddenByLanguage)) {
      applyInterfaceLanguage(language)
      for (const key of translationKeys) {
        expect(t(key), `${language}: ${key}`).not.toMatch(forbidden)
      }
    }
  })
})
