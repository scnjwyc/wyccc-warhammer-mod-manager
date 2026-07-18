<script>
let nextThemedSelectId = 0
</script>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { default: null },
  options: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  ariaLabel: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'change'])
const root = ref(null)
const trigger = ref(null)
const open = ref(false)
const activeIndex = ref(-1)
const listboxId = `themed-select-${++nextThemedSelectId}`

const selectedIndex = computed(() => (
  props.options.findIndex(option => Object.is(option.value, props.modelValue))
))
const selectedOption = computed(() => props.options[selectedIndex.value] || null)
const selectedLabel = computed(() => selectedOption.value?.label ?? '')
const activeOptionId = computed(() => (
  open.value && activeIndex.value >= 0
    ? `${listboxId}-option-${activeIndex.value}`
    : undefined
))

const isEnabled = index => !!props.options[index] && !props.options[index].disabled

const findNextEnabled = (start, direction) => {
  const count = props.options.length
  if (!count) return -1
  for (let offset = 1; offset <= count; offset += 1) {
    const index = (start + (offset * direction) + count) % count
    if (isEnabled(index)) return index
  }
  return -1
}

const openMenu = () => {
  if (props.disabled || !props.options.length) return
  open.value = true
  activeIndex.value = isEnabled(selectedIndex.value)
    ? selectedIndex.value
    : findNextEnabled(-1, 1)
}

const closeMenu = (restoreFocus = false) => {
  open.value = false
  activeIndex.value = -1
  if (restoreFocus) trigger.value?.focus()
}

const toggleMenu = () => {
  if (open.value) closeMenu()
  else openMenu()
}

const selectOption = option => {
  if (props.disabled || option.disabled) return
  emit('update:modelValue', option.value)
  emit('change', option.value)
  closeMenu(true)
}

const handleKeydown = event => {
  if (props.disabled) return

  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) {
      openMenu()
      return
    }
    activeIndex.value = findNextEnabled(activeIndex.value, event.key === 'ArrowDown' ? 1 : -1)
    return
  }

  if (event.key === 'Home' || event.key === 'End') {
    if (!open.value) return
    event.preventDefault()
    activeIndex.value = findNextEnabled(event.key === 'Home' ? -1 : 0, event.key === 'Home' ? 1 : -1)
    return
  }

  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (!open.value) {
      openMenu()
      return
    }
    const option = props.options[activeIndex.value]
    if (option) selectOption(option)
    return
  }

  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    closeMenu(true)
  }
}

const handleDocumentMouseDown = event => {
  if (open.value && !root.value?.contains(event.target)) closeMenu()
}

watch(() => props.disabled, disabled => {
  if (disabled) closeMenu()
})

onMounted(() => document.addEventListener('mousedown', handleDocumentMouseDown))
onBeforeUnmount(() => document.removeEventListener('mousedown', handleDocumentMouseDown))
</script>

<template>
  <div
    ref="root"
    v-bind="$attrs"
    class="themed-select"
    :class="{ open, disabled }"
    @keydown="handleKeydown"
  >
    <button
      ref="trigger"
      type="button"
      class="themed-select-trigger"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="ariaLabel || undefined"
      :aria-expanded="open"
      :aria-controls="listboxId"
      :aria-activedescendant="activeOptionId"
      :disabled="disabled"
      @click="toggleMenu"
    >
      <span class="themed-select-value">{{ selectedLabel }}</span>
      <svg class="themed-select-chevron" viewBox="0 0 12 8" aria-hidden="true">
        <path d="m1 1.5 5 5 5-5"></path>
      </svg>
    </button>

    <div v-if="open" :id="listboxId" class="themed-select-menu" role="listbox">
      <button
        v-for="(option, index) in options"
        :id="`${listboxId}-option-${index}`"
        :key="`${typeof option.value}:${String(option.value)}`"
        type="button"
        class="themed-select-option"
        :class="{
          active: index === activeIndex,
          selected: Object.is(option.value, modelValue),
        }"
        role="option"
        :aria-selected="Object.is(option.value, modelValue)"
        :data-value="String(option.value)"
        :disabled="!!option.disabled"
        @mouseenter="activeIndex = index"
        @click="selectOption(option)"
      >
        <span>{{ option.label }}</span>
        <svg v-if="Object.is(option.value, modelValue)" viewBox="0 0 12 9" aria-hidden="true">
          <path d="m1 4.5 3 3L11 1"></path>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.themed-select {
  position: relative;
  width: 100%;
  min-width: 0;
  color: var(--text);
  user-select: none;
}

.themed-select-trigger {
  display: flex;
  width: 100%;
  min-height: 38px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 11px 0 12px;
  border: 1px solid #594238;
  border-radius: 4px;
  background: linear-gradient(180deg, #171212, #100d0d);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 3%);
  color: #fff5e7;
  cursor: pointer;
  font-weight: 700;
  text-align: left;
  transition: border-color 140ms ease, background 140ms ease, box-shadow 140ms ease;
}

.themed-select-trigger:hover:not(:disabled) {
  border-color: #8b623f;
  background: linear-gradient(180deg, #211816, #15100f);
}

.themed-select.open .themed-select-trigger,
.themed-select-trigger:focus-visible {
  border-color: var(--gold);
  box-shadow: 0 0 0 3px rgb(201 167 106 / 13%), inset 0 1px 0 rgb(255 255 255 / 4%);
  outline: none;
}

.themed-select-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.themed-select-chevron {
  width: 11px;
  flex: 0 0 11px;
  fill: none;
  stroke: #d8c6a6;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.7;
  transition: transform 140ms ease;
}

.themed-select.open .themed-select-chevron {
  transform: rotate(180deg);
}

.themed-select-menu {
  position: absolute;
  z-index: 140;
  top: calc(100% + 4px);
  right: 0;
  left: 0;
  max-height: 260px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid #72503b;
  border-radius: 4px;
  background: #15100f;
  box-shadow: 0 15px 34px rgb(0 0 0 / 58%), inset 0 1px 0 rgb(255 255 255 / 3%);
}

.themed-select-option {
  display: flex;
  width: 100%;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 10px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: #d9cdc2;
  cursor: pointer;
  font-weight: 650;
  text-align: left;
}

.themed-select-option:hover:not(:disabled),
.themed-select-option.active {
  background: #34231e;
  color: #f4dfbc;
}

.themed-select-option.selected {
  background: linear-gradient(90deg, #6e3f29, #4b2d23);
  color: #fff7e8;
}

.themed-select-option.selected.active,
.themed-select-option.selected:hover:not(:disabled) {
  background: linear-gradient(90deg, #855130, #5e3828);
}

.themed-select-option svg {
  width: 12px;
  flex: 0 0 12px;
  fill: none;
  stroke: var(--gold-bright);
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.themed-select.disabled {
  pointer-events: none;
}
</style>
