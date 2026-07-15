import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ModDetails from '../ModDetails.vue'

const sampleMod = {
  id: 'steam:123:sample.pack',
  effective_name: '示例模组',
  display_name: '示例模组',
  pack_name: 'sample.pack',
  path: 'D:\\SteamLibrary\\sample.pack',
  directory: 'D:\\SteamLibrary',
  source: 'workshop',
  workshop_id: '123',
  author: '作者',
  creator_id: '',
  description: '允许展示的模组简介',
  preview_path: '',
  preview_url: '',
  pack_type: 'mod',
  created_at: 1_690_000_000_000,
  updated_at: 1_700_000_000_000,
  alias: '',
  notes: '',
  supported_languages: ['LANGUAGE_FIELD_MUST_NOT_RENDER'],
  file_stats: { files: 'FILE_STATS_FIELD_MUST_NOT_RENDER' },
}

describe('ModDetails', () => {
  it('shows core metadata but ignores excluded detail fields', () => {
    const wrapper = mount(ModDetails, { props: { mod: sampleMod, preview: '' } })
    const text = wrapper.text()

    expect(wrapper.get('[data-testid="mod-details"]').exists()).toBe(true)
    expect(text).toContain('示例模组')
    expect(text).toContain('sample.pack')
    expect(text).toContain('允许展示的模组简介')
    expect(wrapper.get('.details-title .details-meta').text()).toContain('作者')
    expect(wrapper.get('.details-title .details-meta').text()).toContain('创建时间')
    expect(wrapper.find('.details-scroll .detail-grid').exists()).toBe(false)
    expect(text).not.toContain('Pack 类型')
    expect(text).not.toContain('Mod Pack')
    expect(text).not.toContain('支持语言')
    expect(text).not.toContain('文件统计')
    expect(text).not.toContain('LANGUAGE_FIELD_MUST_NOT_RENDER')
    expect(text).not.toContain('FILE_STATS_FIELD_MUST_NOT_RENDER')
    expect(text).toContain('创意工坊页面')
    expect(text).not.toContain('Workshop 页面')
    expect(wrapper.findAll('.button-row .secondary-button').every(button => (
      button.classes().includes('sync-data-button')
    ))).toBe(true)
  })

  it('emits only editable alias and notes as user data', async () => {
    const wrapper = mount(ModDetails, { props: { mod: sampleMod, preview: '' } })
    await wrapper.get('input').setValue('我的别名')
    await wrapper.get('textarea').setValue('我的备注')
    await wrapper.get('button.primary-button').trigger('click')

    expect(wrapper.emitted('save-user-data')).toEqual([
      [sampleMod.id, '我的别名', '我的备注'],
    ])
  })

  it('generates and fills alias and notes through the configured AI action', async () => {
    const generateUserData = async id => ({
      ...sampleMod,
      id,
      alias: 'AI 别名',
      notes: 'AI 备注',
    })
    const wrapper = mount(ModDetails, {
      props: {
        mod: sampleMod,
        preview: '',
        aiEnabled: true,
        generateUserData,
      },
    })

    await wrapper.get('[data-testid="ai-generate-user-data"]').trigger('click')
    await Promise.resolve()
    await Promise.resolve()

    expect(wrapper.get('input').element.value).toBe('AI 别名')
    expect(wrapper.get('textarea').element.value).toBe('AI 备注')
    expect(wrapper.get('[data-testid="ai-generate-user-data"]').attributes('title')).toContain(
      '战锤术语库',
    )
  })

  it('shows the original mod name after the pack name only when an alias is active', () => {
    const aliasedMod = {
      ...sampleMod,
      alias: '山羊控制台（修改版控制台命令）',
      effective_name: '山羊控制台（修改版控制台命令）',
      display_name: 'Goat Console',
      pack_name: 'goat_console.pack',
    }
    const aliased = mount(ModDetails, { props: { mod: aliasedMod, preview: '' } })
    const sourceName = aliased.get('[data-testid="mod-source-name"]')

    expect(sourceName.text()).toBe('goat_console.pack · 原名：Goat Console')
    expect(sourceName.attributes('title')).toBe('goat_console.pack · 原名：Goat Console')

    const original = mount(ModDetails, { props: { mod: sampleMod, preview: '' } })
    expect(original.get('[data-testid="mod-source-name"]').text()).toBe('sample.pack')
    expect(original.text()).not.toContain('原名：')
  })

  it('offers a separate Workshop folder action only for merged Data and Workshop entries', async () => {
    const workshopOnly = mount(ModDetails, { props: { mod: sampleMod, preview: '' } })
    expect(workshopOnly.text()).not.toContain('打开工坊目录')

    const merged = mount(ModDetails, {
      props: {
        mod: {
          ...sampleMod,
          source: 'data',
          sources: ['data', 'workshop'],
          cross_source_duplicate: true,
          path: 'D:\\SteamLibrary\\steamapps\\common\\Total War WARHAMMER III\\data\\sample.pack',
          alternate_paths: ['D:\\SteamLibrary\\steamapps\\workshop\\content\\1142710\\123\\sample.pack'],
        },
        preview: '',
      },
    })
    const button = merged.findAll('button').find(item => item.text() === '打开工坊目录')

    expect(button).toBeDefined()
    await button.trigger('click')
    expect(merged.emitted('open-workshop-folder')).toEqual([[sampleMod.id]])
  })

  it('explains when workshop author metadata has not been fetched', () => {
    const wrapper = mount(ModDetails, {
      props: { mod: { ...sampleMod, author: '', creator_id: '' }, preview: '' },
    })
    expect(wrapper.get('.details-meta').text()).toContain('未获取（后台刷新工坊信息）')
  })

  it('does not substitute a numeric Steam ID for the author nickname', () => {
    const wrapper = mount(ModDetails, {
      props: {
        mod: { ...sampleMod, author: '', creator_id: '76561198000000000' },
        preview: '',
      },
    })
    expect(wrapper.get('.details-meta').text()).toContain('作者昵称暂不可用')
    expect(wrapper.get('.details-meta').text()).not.toContain('76561198000000000')
  })

  it('renders Steam Workshop headings and lists instead of showing raw tags', () => {
    const wrapper = mount(ModDetails, {
      props: {
        mod: {
          ...sampleMod,
          description: '[h1]主要功能[/h1]\n[list][*]第一项[*][b]第二项[/b][/list]',
        },
        preview: '',
      },
    })
    const description = wrapper.get('[data-testid="workshop-description"]')

    expect(description.get('.workshop-heading-1').text()).toBe('主要功能')
    expect(description.findAll('.workshop-list li').map(item => item.text())).toEqual([
      '第一项',
      '第二项',
    ])
    expect(description.get('strong').text()).toBe('第二项')
    expect(description.text()).not.toContain('[h1]')
    expect(description.text()).not.toContain('[list]')
  })
})
