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

  it('shows the supported unit multiplier range in every language', () => {
    const expectedRanges = {
      'zh-CN': '0.5–5',
      'en-US': '0.5–5',
      'ko-KR': '0.5–5',
      'ru-RU': '0,5–5',
      'ja-JP': '0.5～5',
    }

    for (const [language, expectedRange] of Object.entries(expectedRanges)) {
      applyInterfaceLanguage(language)
      expect(t('gameData.unitMultiplierHelp'), language).toContain(expectedRange)
    }
  })

  it('describes explicit game-data patch generation in every language', () => {
    const expected = {
      'zh-CN': { button: '生成补丁', busy: '生成游戏数据补丁', intro: '点击', reminder: '新增或删除涉及兵模数量或友伤的 MOD 后，必须重新生成补丁。' },
      'en-US': { button: 'Generate patch', busy: 'Generating game data patch', intro: 'Generate patch', reminder: 'After adding or removing any MOD that affects model counts or friendly fire, you must generate the patch again.' },
      'ko-KR': { button: '패치 생성', busy: '게임 데이터 패치 생성 중', intro: '패치 생성', reminder: '모델 수 또는 아군 피해에 영향을 주는 MOD를 추가하거나 제거한 뒤에는 반드시 패치를 다시 생성해야 합니다.' },
      'ru-RU': { button: 'Создать патч', busy: 'Создание патча игровых данных', intro: 'Создать патч', reminder: 'После добавления или удаления MOD, влияющего на численность моделей или урон союзникам, обязательно создайте патч заново.' },
      'ja-JP': { button: 'パッチを生成', busy: 'ゲームデータパッチを生成中', intro: 'パッチを生成', reminder: '兵数または味方ダメージに影響する MOD を追加・削除した後は、必ずパッチを再生成してください。' },
    }

    for (const [language, labels] of Object.entries(expected)) {
      applyInterfaceLanguage(language)
      expect(t('gameData.generatePatch'), `${language}: button`).toBe(labels.button)
      expect(t('busy.generateGameDataPatch'), `${language}: busy`).toBe(labels.busy)
      expect(t('gameData.intro'), `${language}: intro`).toContain(labels.intro)
      expect(t('gameData.regenerateAfterModChanges'), `${language}: reminder`).toBe(labels.reminder)
      expect(`${t('gameData.intro')} ${t('gameData.runtimeNote')}`, language)
        .not.toMatch(/启动游戏时|when the game launches|게임 실행 시|При запуске|ゲーム起動時/u)
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
