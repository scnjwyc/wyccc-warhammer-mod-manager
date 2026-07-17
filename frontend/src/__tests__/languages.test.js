// @vitest-environment jsdom

import { readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_LANGUAGE,
  applyInterfaceLanguage,
  hasTranslation,
  localizeBackendMessage,
  t,
  translationKeys,
} from '../languages'

const here = dirname(fileURLToPath(import.meta.url))
const sourceRoot = resolve(here, '..')
const languageCodes = ['zh-CN', 'en-US', 'ko-KR', 'ru-RU', 'ja-JP']

const sourceFiles = directory => readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
  const path = resolve(directory, entry.name)
  if (entry.isDirectory()) return entry.name === '__tests__' ? [] : sourceFiles(path)
  return ['.js', '.vue'].some(extension => entry.name.endsWith(extension)) && entry.name !== 'languages.js'
    ? [path]
    : []
})

const localizedValues = key => languageCodes.map(language => {
  applyInterfaceLanguage(language)
  return t(key)
})

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

  it('provides a catalog entry for every static translation key used by the interface', () => {
    const usedKeys = new Set()
    const keyPattern = /(?<![A-Za-z0-9_])t\(\s*(['"])([^'"]+)\1/g

    for (const path of sourceFiles(sourceRoot)) {
      const source = readFileSync(path, 'utf8')
      for (const match of source.matchAll(keyPattern)) usedKeys.add(match[2])
    }

    expect([...usedKeys].filter(key => !translationKeys.includes(key)).sort()).toEqual([])
  })

  it('uses the same placeholders in every language variant', () => {
    const placeholders = value => [...value.matchAll(/\{([A-Za-z0-9_]+)\}/g)]
      .map(match => match[1])
      .sort()

    for (const key of translationKeys) {
      const variants = localizedValues(key)
      const expected = placeholders(variants[0])
      for (const [index, variant] of variants.entries()) {
        expect(placeholders(variant), `${languageCodes[index]}: ${key}`).toEqual(expected)
      }
    }
  })

  it('uses complete and natural translations for corrected 0.6.0 labels', () => {
    const expected = {
      'en-US': {
        'app.gameDataModification': 'Game data modification',
      },
      'ru-RU': {
        'app.gameDataModification': 'Изменение игровых данных',
      },
      'ja-JP': {
        'official.missing': 'ローカルに未インストール',
        'saves.compareCurrentOnly': '現在有効、セーブには含まれない',
      },
    }

    for (const [language, labels] of Object.entries(expected)) {
      applyInterfaceLanguage(language)
      for (const [key, value] of Object.entries(labels)) expect(t(key), `${language}: ${key}`).toBe(value)
    }
  })

  it('describes the 1-5 integer unit-scale control and character-health option in every language', () => {
    const expectedRanges = {
      'zh-CN': '1–5',
      'en-US': '1–5',
      'ko-KR': '1–5',
      'ru-RU': '1–5',
      'ja-JP': '1～5',
    }

    for (const [language, expectedRange] of Object.entries(expectedRanges)) {
      applyInterfaceLanguage(language)
      expect(t('gameData.unitMultiplierHelp'), language).toContain(expectedRange)
      expect(t('gameData.scaleLordHeroHealth'), language).not.toBe('gameData.scaleLordHeroHealth')
      expect(t('gameData.scaleLordHeroHealthHelp'), language).not.toBe('gameData.scaleLordHeroHealthHelp')
    }
    applyInterfaceLanguage('zh-CN')
    expect(t('gameData.unitMultiplier')).toBe('单位规模倍率')
  })

  it('describes launch-time game-data patch validation in every language', () => {
    const expected = {
      'zh-CN': ['启动游戏时', '配置组或顺序', '源 Pack', 'db.pack', '自动重新生成'],
      'en-US': ['launched through this manager', 'playset or order', 'source Packs', 'db.pack', 'automatically regenerated'],
      'ko-KR': ['이 관리자로 게임을 실행할 때', '플레이 세트 또는 순서', '원본 Pack', 'db.pack', '자동으로 다시 생성'],
      'ru-RU': ['запуске игры через этот менеджер', 'набора или порядка', 'исходных Pack', 'db.pack', 'автоматически пересоздаётся'],
      'ja-JP': ['このマネージャーからゲームを起動する際', 'プレイセットまたは順序', '元の Pack', 'db.pack', '自動的に再生成'],
    }

    for (const [language, terms] of Object.entries(expected)) {
      applyInterfaceLanguage(language)
      const copy = t('gameData.autoGenerateOnLaunch')
      for (const term of terms) expect(copy, `${language}: ${term}`).toContain(term)
    }
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

  it('describes a force update as waiting for and completing the download', () => {
    applyInterfaceLanguage('zh-CN')
    expect(t('busy.forceUpdateWorkshop')).toContain('等待')
    expect(t('toast.forceUpdateCompleted')).toContain('完成')
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
