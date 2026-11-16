<script setup>
import { computed } from 'vue'
import { t } from '../languages'

const props = defineProps({
  open: Boolean, x: Number, y: Number, busy: Boolean, gameRunning: Boolean,
})
const emit = defineEmits(['close', 'action'])
const style = computed(() => ({
  left: `${Math.max(8, Math.min(props.x, window.innerWidth - 254))}px`,
  top: `${Math.max(8, Math.min(props.y, window.innerHeight - 210))}px`,
}))
const actions = ['rename', 'release', 'delete', 'unsubscribe']
const run = action => { emit('close'); emit('action', action) }
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="context-menu-layer" @mousedown.self="emit('close')"
      @contextmenu.prevent="emit('close')" @keydown.esc="emit('close')">
      <nav class="context-menu" :style="style" role="menu" :aria-label="t('folders.menu')">
        <button v-for="action in actions" :key="action" type="button" class="context-menu-item"
          role="menuitem" :data-testid="`folder-action-${action}`"
          :disabled="busy || (action === 'unsubscribe' && gameRunning)" @click="run(action)">
          <span class="context-menu-icon">{{ action === 'unsubscribe' ? '!' : '▣' }}</span>
          <span>{{ t(`folders.${action === 'delete' ? 'deleteHelp' : action}`) }}</span>
        </button>
      </nav>
    </div>
  </Teleport>
</template>
