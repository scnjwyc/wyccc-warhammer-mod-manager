import { describe, expect, it } from 'vitest'

import {
  getSearchSuggestions,
  insertByDefaultLoadOrder,
  matchesSearchTokens,
  parseSearchToken,
  sortDisplayedMods,
} from '../modSearch'
import { applyInterfaceLanguage } from '../languages'

const typeMap = {
  language: '语言包',
  ui: 'UI',
  unknown: '未知',
}

const mods = [
  {
    id: 'a',
    effective_name: '震旦兵种扩展',
    pack_name: 'cth_units.pack',
    author: 'Wyccc',
    source: 'data',
    mod_types: ['language', 'ui'],
    updated_at: 200,
    created_at: 100,
  },
  {
    id: 'b',
    effective_name: 'Empire Overhaul',
    pack_name: 'empire.pack',
    author: 'Other Author',
    source: 'workshop',
    mod_types: ['unknown'],
    updated_at: 100,
    created_at: 300,
  },
]

describe('RimCrow-style multi-condition MOD search', () => {
  it('parses fields, Chinese aliases, plain text and exclusions', () => {
    expect(parseSearchToken('类型:语言包')).toMatchObject({
      type: 'rule',
      key: 'type',
      value: '语言包',
      exclude: false,
    })
    expect(parseSearchToken('-author:Other')).toMatchObject({
      type: 'rule',
      key: 'author',
      value: 'Other',
      exclude: true,
    })
    expect(parseSearchToken('震旦')).toMatchObject({ type: 'text', value: '震旦' })
    expect(parseSearchToken('type:')).toBeNull()
  })

  it('parses and suggests Spanish search syntax', () => {
    applyInterfaceLanguage('es-ES')

    expect(parseSearchToken('nombre:Empire')).toMatchObject({
      type: 'rule',
      key: 'name',
      value: 'Empire',
    })
    expect(getSearchSuggestions('')[0].value).toBe('nombre:')

    applyInterfaceLanguage('zh-CN')
  })

  it('supports multiple type-aware conditions with AND, OR and exclusion', () => {
    const typeToken = parseSearchToken('type:语言包')
    const authorToken = parseSearchToken('author:Wyccc')
    const excludedSource = parseSearchToken('-source:workshop')

    expect(matchesSearchTokens(mods[0], [typeToken, authorToken, excludedSource], 'AND', typeMap)).toBe(true)
    expect(matchesSearchTokens(mods[1], [typeToken, authorToken], 'AND', typeMap)).toBe(false)
    expect(matchesSearchTokens(mods[1], [typeToken, parseSearchToken('name:Empire')], 'OR', typeMap)).toBe(true)
  })
})

describe('display-only sorting', () => {
  it('sorts by the persisted primary MOD type order', () => {
    const original = [
      { id: 'ui', pack_name: 'a.pack', mod_types: ['ui'] },
      { id: 'unknown', pack_name: 'z.pack', mod_types: ['unknown'] },
      { id: 'overhaul', pack_name: 'c.pack', mod_types: ['overhaul'] },
      { id: 'multi', pack_name: 'b.pack', mod_types: ['ui', 'overhaul'] },
    ]
    const ranks = { overhaul: 0, ui: 1, unknown: 2 }

    expect(sortDisplayedMods(original, 'type', false, ranks).map(mod => mod.id)).toEqual([
      'overhaul', 'ui', 'multi', 'unknown',
    ])
    expect(sortDisplayedMods(original, 'type', true, ranks).map(mod => mod.id)).toEqual([
      'unknown', 'multi', 'ui', 'overhaul',
    ])
  })

  it('sorts a copied list and keeps priority order unchanged', () => {
    const original = [mods[1], mods[0]]
    const byFile = sortDisplayedMods(original, 'filename', false)
    const byUpdated = sortDisplayedMods(original, 'updated', true)

    expect(byFile.map(mod => mod.id)).toEqual(['a', 'b'])
    expect(byUpdated.map(mod => mod.id)).toEqual(['a', 'b'])
    expect(sortDisplayedMods(original, 'priority', false)).toEqual(original)
    expect(original.map(mod => mod.id)).toEqual(['b', 'a'])
    expect(byFile).not.toBe(original)
  })
})

describe('default load-order placement', () => {
  it('inserts a newly enabled MOD by case-insensitive Pack filename', () => {
    const modsById = new Map([
      ['units', { id: 'units', pack_name: 'cth_units.pack' }],
      ['zeta', { id: 'zeta', pack_name: 'zeta.pack' }],
      ['patch', { id: 'patch', pack_name: '!compat_patch.pack' }],
      ['middle', { id: 'middle', pack_name: 'miao.pack' }],
    ])

    expect(insertByDefaultLoadOrder(['units', 'zeta'], 'patch', modsById)).toEqual([
      'patch', 'units', 'zeta',
    ])
    expect(insertByDefaultLoadOrder(['units', 'zeta'], 'middle', modsById)).toEqual([
      'units', 'middle', 'zeta',
    ])
  })

  it('does not reshuffle existing manual positions while adding the new MOD', () => {
    const modsById = new Map([
      ['zeta', { id: 'zeta', pack_name: 'zeta.pack' }],
      ['alpha', { id: 'alpha', pack_name: 'alpha.pack' }],
      ['middle', { id: 'middle', pack_name: 'middle.pack' }],
    ])

    expect(insertByDefaultLoadOrder(['zeta', 'alpha'], 'middle', modsById)).toEqual([
      'middle', 'zeta', 'alpha',
    ])
  })
})
