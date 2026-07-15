<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import { t } from '../languages'
import {
  getSearchSuggestions,
  parseSearchToken,
  SEARCH_FIELDS,
  searchFieldLabel,
  searchTokenIdentity,
} from '../modSearch'

const props = defineProps({
  tokens: { type: Array, default: () => [] },
  logic: { type: String, default: 'AND' },
  mods: { type: Array, default: () => [] },
  typeMap: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update:tokens', 'update:logic'])
const inputValue = ref('')
const showSuggestions = ref(false)
const highlightedIndex = ref(0)
const inputRef = ref(null)
let blurTimer = 0

const suggestions = computed(() => getSearchSuggestions(inputValue.value, props.mods, props.typeMap))
const placeholder = computed(() => props.tokens.length ? t('search.addCondition') : t('search.placeholder'))

const addToken = rawValue => {
  const token = parseSearchToken(rawValue ?? inputValue.value)
  if (!token) return
  const identity = searchTokenIdentity(token)
  if (!props.tokens.some(item => searchTokenIdentity(item) === identity)) {
    emit('update:tokens', [...props.tokens, { ...token, id: `${Date.now()}-${Math.random()}` }])
  }
  inputValue.value = ''
  showSuggestions.value = false
}

const applySuggestion = suggestion => {
  if (suggestion.type === 'key') {
    inputValue.value = suggestion.value
    showSuggestions.value = true
    highlightedIndex.value = 0
    nextTick(() => inputRef.value?.focus())
    return
  }
  addToken(suggestion.value)
  nextTick(() => inputRef.value?.focus())
}

const removeToken = index => {
  const nextTokens = [...props.tokens]
  nextTokens.splice(index, 1)
  emit('update:tokens', nextTokens)
  nextTick(() => inputRef.value?.focus())
}

const clearAll = () => {
  inputValue.value = ''
  emit('update:tokens', [])
  nextTick(() => inputRef.value?.focus())
}

const handleKeydown = event => {
  if (event.key === 'Enter') {
    event.preventDefault()
    addToken()
  } else if (event.key === 'Tab' && showSuggestions.value && suggestions.value.length) {
    event.preventDefault()
    applySuggestion(suggestions.value[highlightedIndex.value])
  } else if (event.key === 'Backspace' && !inputValue.value && props.tokens.length) {
    removeToken(props.tokens.length - 1)
  } else if (event.key === 'ArrowDown' && suggestions.value.length) {
    event.preventDefault()
    highlightedIndex.value = Math.min(highlightedIndex.value + 1, suggestions.value.length - 1)
  } else if (event.key === 'ArrowUp' && suggestions.value.length) {
    event.preventDefault()
    highlightedIndex.value = Math.max(highlightedIndex.value - 1, 0)
  } else if (event.key === 'Escape') {
    showSuggestions.value = false
  }
}

const handleBlur = () => {
  window.clearTimeout(blurTimer)
  blurTimer = window.setTimeout(() => { showSuggestions.value = false }, 180)
}

const tokenLabel = token => {
  const field = token.key ? SEARCH_FIELDS[token.key] : null
  return `${token.exclude ? '-' : ''}${field ? `${searchFieldLabel(field)}:` : ''}${token.displayValue ?? token.value}`
}

onBeforeUnmount(() => window.clearTimeout(blurTimer))
</script>

<template>
  <div class="search-box tag-search-box" data-testid="tag-search-box">
    <button
      type="button"
      class="search-logic-button"
      :class="logic.toLocaleLowerCase()"
      :title="logic === 'AND' ? t('search.logicAll') : t('search.logicAny')"
      @click="emit('update:logic', logic === 'AND' ? 'OR' : 'AND')"
    >
      {{ logic === 'AND' ? t('search.logicAllShort') : t('search.logicAnyShort') }}
    </button>
    <span class="search-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" focusable="false">
        <circle cx="10.5" cy="10.5" r="6.5"></circle>
        <path d="m15.4 15.4 4.1 4.1"></path>
      </svg>
    </span>
    <div class="search-token-scroll">
      <span
        v-for="(token, index) in tokens"
        :key="token.id || searchTokenIdentity(token)"
        class="search-token"
        :class="{ excluded: token.exclude, rule: token.type === 'rule' }"
        :title="tokenLabel(token)"
      >
        <span>{{ tokenLabel(token) }}</span>
        <button type="button" :aria-label="t('search.removeCondition', { label: tokenLabel(token) })" @click="removeToken(index)">×</button>
      </span>
      <input
        ref="inputRef"
        v-model="inputValue"
        type="text"
        :placeholder="placeholder"
        :aria-label="t('search.aria')"
        @focus="showSuggestions = true"
        @input="highlightedIndex = 0; showSuggestions = true"
        @keydown="handleKeydown"
        @blur="handleBlur"
      />
    </div>
    <button
      v-if="tokens.length || inputValue"
      type="button"
      class="search-clear-button"
      :title="t('search.clear')"
      :aria-label="t('search.clear')"
      @click="clearAll"
    >×</button>

    <div v-if="showSuggestions && suggestions.length" class="search-suggestions" role="listbox">
      <button
        v-for="(suggestion, index) in suggestions"
        :key="suggestion.value"
        type="button"
        :class="{ highlighted: highlightedIndex === index }"
        @mousedown.prevent="applySuggestion(suggestion)"
        @mouseenter="highlightedIndex = index"
      >
        <span class="suggestion-kind">{{ suggestion.type === 'key' ? t('search.suggestionKey') : t('search.suggestionValue') }}</span>
        <span class="suggestion-value">{{ suggestion.value }}</span>
        <span class="suggestion-description">{{ suggestion.type === 'value' ? suggestion.label : suggestion.label }}</span>
      </button>
    </div>
  </div>
</template>
