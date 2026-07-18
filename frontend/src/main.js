import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './styles.css'

let mounted = false
try {
  createApp(App).use(createPinia()).mount('#app')
  mounted = true
} catch (error) {
  window.__wmmShowStartupError?.(error)
} finally {
  if (mounted) document.getElementById('startup-fallback')?.remove()
}
