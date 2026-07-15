const normalize = value => String(value ?? '').trim().toLocaleLowerCase()

const fieldDefinitions = [
  { key: 'name', label: '模组名', aliases: ['名称', '模组', 'mod'], defaultSearch: true },
  { key: 'file', label: '文件名', aliases: ['文件', '包名', 'pack'], defaultSearch: true },
  { key: 'author', label: '作者', aliases: ['作者名'], defaultSearch: true, suggest: true },
  { key: 'type', label: '类型', aliases: ['类型', 'mod_type'], suggest: true },
  { key: 'source', label: '来源', aliases: ['来源', '位置'], suggest: true },
  { key: 'workshop', label: 'Workshop ID', aliases: ['工坊', 'workshop_id'], defaultSearch: true },
  { key: 'creator', label: '作者 ID', aliases: ['作者id', 'creator_id'], defaultSearch: true },
]

export const SEARCH_FIELDS = Object.fromEntries(fieldDefinitions.map(field => [field.key, field]))

const fieldAliases = new Map()
for (const field of fieldDefinitions) {
  for (const alias of [field.key, ...field.aliases]) fieldAliases.set(normalize(alias), field.key)
}

export const SORT_OPTIONS = [
  { id: 'priority', label: '优先级' },
  { id: 'filename', label: '文件名' },
  { id: 'name', label: '模组名' },
  { id: 'author', label: '作者' },
  { id: 'updated', label: '更新时间' },
  { id: 'created', label: '创建时间' },
]

const selectedTypeIds = mod => (
  Array.isArray(mod?.mod_types) && mod.mod_types.length
    ? mod.mod_types
    : [mod?.mod_type || 'unknown']
)

const valuesFor = (mod, key, typeMap = {}) => {
  if (key === 'name') return [mod?.effective_name, mod?.display_name, mod?.alias]
  if (key === 'file') return [mod?.pack_name]
  if (key === 'author') return [mod?.author]
  if (key === 'type') {
    return selectedTypeIds(mod).flatMap(typeId => [typeId, typeMap[typeId] || typeId])
  }
  if (key === 'source') return mod?.sources?.length ? mod.sources : [mod?.source]
  if (key === 'workshop') return [mod?.workshop_id]
  if (key === 'creator') return [mod?.creator_id]
  return []
}

export const parseSearchToken = rawInput => {
  const input = String(rawInput || '').trim()
  if (!input) return null
  const rule = input.match(/^(-?)([^:]+):(.*)$/)
  if (rule) {
    const [, excludePrefix, rawKey, rawValue] = rule
    const key = fieldAliases.get(normalize(rawKey))
    if (key) {
      const value = rawValue.trim()
      if (!value) return null
      return {
        type: 'rule',
        key,
        originalKey: rawKey,
        value,
        displayValue: value,
        exclude: excludePrefix === '-',
      }
    }
  }
  const exclude = input.startsWith('-')
  const value = (exclude ? input.slice(1) : input).trim()
  if (!value) return null
  return { type: 'text', key: null, value, displayValue: value, exclude }
}

export const searchTokenIdentity = token => [
  token?.type || '',
  token?.key || '',
  normalize(token?.value),
  token?.exclude ? 'exclude' : 'include',
].join('|')

const tokenMatches = (mod, token, typeMap) => {
  const keys = token.type === 'rule'
    ? [token.key]
    : fieldDefinitions.filter(field => field.defaultSearch).map(field => field.key)
  const needle = normalize(token.value)
  const matched = Boolean(needle) && keys.some(key => (
    valuesFor(mod, key, typeMap).some(value => normalize(value).includes(needle))
  ))
  return token.exclude ? !matched : matched
}

export const matchesSearchTokens = (mod, tokens = [], logic = 'AND', typeMap = {}) => {
  if (!tokens.length) return true
  const results = tokens.map(token => tokenMatches(mod, token, typeMap))
  return logic === 'OR' ? results.some(Boolean) : results.every(Boolean)
}

const suggestionValues = (key, mods, typeMap) => {
  if (key === 'type') return Object.entries(typeMap).map(([value, label]) => ({ value: label, label }))
  if (key === 'source') {
    return [
      { value: 'data', label: 'Data' },
      { value: 'workshop', label: 'Workshop' },
    ]
  }
  const values = new Set()
  for (const mod of mods || []) {
    for (const value of valuesFor(mod, key, typeMap)) {
      const cleanValue = String(value || '').trim()
      if (cleanValue) values.add(cleanValue)
    }
  }
  return [...values].map(value => ({ value, label: value }))
}

const keySuggestion = (field, exclude = false) => ({
  type: 'key',
  label: field.label,
  value: `${exclude ? '-' : ''}${field.key}:`,
  description: `${field.key}:关键词`,
})

export const getSearchSuggestions = (rawInput = '', mods = [], typeMap = {}) => {
  const input = String(rawInput || '').trim()
  if (!input) return fieldDefinitions.map(field => keySuggestion(field))

  const valueRule = input.match(/^(-?)([^:]+):(.*)$/)
  if (valueRule) {
    const [, excludePrefix, rawKey, rawValue] = valueRule
    const key = fieldAliases.get(normalize(rawKey))
    const field = SEARCH_FIELDS[key]
    if (!field?.suggest) return []
    const needle = normalize(rawValue)
    return suggestionValues(key, mods, typeMap)
      .filter(option => !needle || normalize(option.label).includes(needle) || normalize(option.value).includes(needle))
      .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN', { numeric: true }))
      .slice(0, 40)
      .map(option => ({
        type: 'value',
        label: option.label,
        value: `${excludePrefix}${field.key}:${option.value}`,
        description: field.label,
      }))
  }

  const exclude = input.startsWith('-')
  const prefix = normalize(exclude ? input.slice(1) : input)
  return fieldDefinitions
    .filter(field => [field.key, ...field.aliases].some(alias => normalize(alias).startsWith(prefix)))
    .map(field => keySuggestion(field, exclude))
}

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

// Pack filenames are the manager's deterministic default load-order rule.  Keep
// this deliberately bytewise (rather than locale-aware) so prefixes such as
// "!" retain the same priority users and mod authors expect on every machine.
const defaultLoadOrderKey = mod => [
  String(mod?.pack_name || '').toLowerCase(),
  String(mod?.id || '').toLowerCase(),
]

export const compareDefaultLoadOrder = (left, right) => {
  const [leftName, leftId] = defaultLoadOrderKey(left)
  const [rightName, rightId] = defaultLoadOrderKey(right)
  if (leftName < rightName) return -1
  if (leftName > rightName) return 1
  if (leftId < rightId) return -1
  if (leftId > rightId) return 1
  return 0
}

const modForId = (modsById, id) => (
  modsById instanceof Map ? modsById.get(id) : modsById?.[id]
)

// Only the newly enabled MOD is placed by the default rule. Existing entries
// stay in their relative order so a user's hand-tuned load order is never reset.
export const insertByDefaultLoadOrder = (orderedIds = [], modId, modsById = {}) => {
  if (!modId || orderedIds.includes(modId)) return [...orderedIds]
  const candidate = modForId(modsById, modId)
  if (!candidate) return [...orderedIds, modId]
  const insertAt = orderedIds.findIndex(existingId => (
    compareDefaultLoadOrder(candidate, modForId(modsById, existingId)) < 0
  ))
  const next = [...orderedIds]
  next.splice(insertAt < 0 ? next.length : insertAt, 0, modId)
  return next
}

export const sortDisplayedMods = (mods, mode = 'priority', descending = false) => {
  const result = [...(mods || [])]
  if (mode === 'priority') return result
  const compareText = (left, right) => collator.compare(String(left || ''), String(right || ''))
  result.sort((left, right) => {
    let comparison = 0
    if (mode === 'filename') comparison = compareText(left.pack_name, right.pack_name)
    else if (mode === 'name') comparison = compareText(left.effective_name, right.effective_name)
    else if (mode === 'author') comparison = compareText(left.author, right.author)
    else if (mode === 'updated') comparison = Number(left.updated_at || 0) - Number(right.updated_at || 0)
    else if (mode === 'created') comparison = Number(left.created_at || 0) - Number(right.created_at || 0)
    if (comparison === 0) comparison = compareText(left.pack_name, right.pack_name)
    return descending ? -comparison : comparison
  })
  return result
}
