import { afterEach, describe, expect, it } from 'vitest'

import {
  applyInterfaceLanguage,
  hasTranslation,
  localizeBackendMessage,
  t,
} from '../languages'

const playsetJsonKeys = [
  'share.jsonSection',
  'share.exportJson',
  'share.importJson',
  'share.includeDescriptions',
  'share.importMode',
  'share.importModeNew',
  'share.importModeCurrent',
  'share.jsonHelp',
  'share.exportJsonDone',
  'share.exportJsonDoneLarge',
  'share.importJsonDone',
  'share.importJsonMissing',
  'share.importJsonNoMods',
  'share.importJsonWrongGame',
  'share.importJsonTooLarge',
  'share.importJsonInvalid',
  'share.importJsonNotPlayset',
  'share.importJsonBadVersion',
  'share.importJsonMissingMods',
  'share.importJsonFileMissing',
  'share.importJsonUnsupportedMode',
  'share.importJsonCreateFailed',
  'share.exportJsonDialogFailed',
  'share.importJsonDialogFailed',
]

describe('playset JSON translations', () => {
  afterEach(() => applyInterfaceLanguage('en-US'))

  it('provides every playset JSON key in all six languages', () => {
    for (const key of playsetJsonKeys) {
      expect(hasTranslation(key), key).toBe(true)
    }
  })

  it('localizes playset JSON backend errors', () => {
    applyInterfaceLanguage('en-US')
    expect(localizeBackendMessage('播放集 JSON 文件不存在')).toBe(
      t('share.importJsonFileMissing'),
    )
    expect(localizeBackendMessage('播放集 JSON 所属游戏与当前游戏不一致')).toBe(
      t('share.importJsonWrongGame'),
    )
    expect(localizeBackendMessage('无法打开播放集导入对话框：测试')).toBe(
      t('share.importJsonDialogFailed', { error: '测试' }),
    )
    applyInterfaceLanguage('zh-CN')
    expect(localizeBackendMessage('播放集 JSON 格式无效')).toBe(
      t('share.importJsonInvalid'),
    )
  })
})
