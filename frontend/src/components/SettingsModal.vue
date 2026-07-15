<script setup>
import { reactive, watch } from 'vue'
import { DEFAULT_LANGUAGE, LANGUAGE_OPTIONS } from '../languages'
import { useAppStore } from '../store'

const props = defineProps({
  open: { type: Boolean, default: false },
  settings: { type: Object, default: () => ({}) },
  health: { type: Object, default: () => ({}) },
  busy: { type: String, default: '' },
})

const emit = defineEmits(['close', 'save', 'detect', 'check-update', 'show-changelog'])
const store = useAppStore()
const draft = reactive({})

watch(
  () => [props.open, props.settings],
  () => {
    Object.keys(draft).forEach(key => delete draft[key])
    Object.assign(draft, props.settings)
    if (!draft.language) draft.language = DEFAULT_LANGUAGE
    draft.clear_ai_api_key = false
  },
  { immediate: true, deep: true },
)

const browse = async kind => {
  const result = await store.selectDirectory(kind)
  if (!result.path) return
  if (kind === 'game') draft.game_path = result.path
  else draft.workshop_path = result.path
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @mousedown.self="emit('close')">
    <section class="modal-card settings-modal" role="dialog" aria-modal="true" aria-label="设置">
      <header class="modal-header">
        <div>
          <span class="eyebrow">CONFIGURATION</span>
          <h2>管理器设置</h2>
        </div>
        <button type="button" class="icon-button" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <div class="health-card" :class="{ healthy: health.game_ready }">
          <span class="health-dot"></span>
          <div>
            <strong>{{ health.game_ready ? 'Warhammer III 路径有效' : '尚未找到有效游戏目录' }}</strong>
            <p>需要包含 Warhammer3.exe 和 data 目录。</p>
          </div>
          <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('detect')">
            自动检测 Steam
          </button>
        </div>

        <label class="field-label language-field">
          <span>界面语言</span>
          <select v-model="draft.language" data-testid="language-select">
            <option v-for="language in LANGUAGE_OPTIONS" :key="language.code" :value="language.code">
              {{ language.label }}
            </option>
          </select>
          <small class="field-help">管理器界面暂时统一使用中文；Workshop 标题和描述会优先使用所选语言，缺失时回退英文。</small>
        </label>

        <label class="field-label">
          <span>游戏目录</span>
          <div class="path-input-row">
            <input v-model="draft.game_path" type="text" placeholder="...\steamapps\common\Total War WARHAMMER III" />
            <button type="button" class="secondary-button" @click="browse('game')">浏览</button>
          </div>
        </label>

        <label class="field-label">
          <span>Workshop 内容目录</span>
          <div class="path-input-row">
            <input v-model="draft.workshop_path" type="text" placeholder="...\workshop\content\1142710" />
            <button type="button" class="secondary-button" @click="browse('workshop')">浏览</button>
          </div>
        </label>

        <div class="settings-section">
          <h3>工坊与检查</h3>
          <p class="settings-scan-note">MOD 扫描固定覆盖游戏 Data 与 Steam Workshop。</p>
          <label class="switch-row">
            <input v-model="draft.fetch_workshop_metadata" type="checkbox" />
            <span><strong>启动时后台刷新工坊信息</strong><small>自动获取标题、作者昵称、发布时间和预览图；关闭后仍可从主界面手动刷新</small></span>
          </label>
          <label class="switch-row">
            <input v-model="draft.check_outdated_mods" type="checkbox" data-testid="check-outdated-mods" />
            <span><strong>检查过期 MOD</strong><small>默认关闭；启用后，当游戏本体最后更新时间早于 MOD 最后更新时间时，将该 MOD 加入警告</small></span>
          </label>
        </div>

        <div class="settings-section">
          <h3>AI 生成</h3>
          <label class="switch-row">
            <input v-model="draft.ai_enabled" type="checkbox" data-testid="ai-enabled" />
            <span><strong>启用 AI 生成当前语言标题和摘要备注</strong><small>标题直接翻译；备注先结合标题总结原简介，再翻译为当前设置语言</small></span>
          </label>
          <div class="settings-field-grid" :class="{ disabled: !draft.ai_enabled }">
            <label class="field-label settings-wide-field">
              <span>OpenAI-compatible Base URL</span>
              <input v-model="draft.ai_base_url" type="url" data-testid="ai-base-url" placeholder="https://api.openai.com/v1" />
            </label>
            <label class="field-label">
              <span>模型</span>
              <input v-model="draft.ai_model" type="text" data-testid="ai-model" placeholder="填写服务商提供的模型名称" />
            </label>
            <label class="field-label">
              <span>温度</span>
              <input v-model.number="draft.ai_temperature" type="number" min="0" max="2" step="0.1" data-testid="ai-temperature" />
            </label>
            <label class="field-label settings-wide-field">
              <span>API Key</span>
              <input
                v-model="draft.ai_api_key"
                type="password"
                data-testid="ai-api-key"
                :placeholder="draft.ai_api_key_configured ? '已保存；留空保持不变' : '本地服务无需密钥时可留空'"
                autocomplete="new-password"
              />
            </label>
            <label v-if="draft.ai_api_key_configured" class="clear-secret-row settings-wide-field">
              <input v-model="draft.clear_ai_api_key" type="checkbox" />
              清除已保存的 API Key
            </label>
          </div>
          <small class="field-help">优先复用本地战锤术语库，未命中时由 AI 根据原文直接翻译；不联网搜索、不查询原版 LOC。支持 OpenAI-compatible Chat Completions 接口，API Key 仅保存在本机。</small>
        </div>

        <div class="settings-section software-update-settings">
          <h3>软件更新</h3>
          <label class="switch-row">
            <input v-model="draft.check_updates_automatically" type="checkbox" data-testid="auto-update-check" />
            <span><strong>启动时自动检查更新</strong><small>每 24 小时最多检查一次；只提示新版本，不会静默下载或安装</small></span>
          </label>
          <label class="field-label update-manifest-field">
            <span>更新清单地址</span>
            <input
              v-model="draft.update_manifest_url"
              type="url"
              data-testid="update-manifest-url"
              placeholder="https://example.com/update-manifest.json"
            />
            <small class="field-help">发布者应在正式版中内置 HTTPS JSON 地址；也可在这里切换私有更新通道。手动检查会立即采用并保存当前地址。</small>
          </label>
          <div class="settings-inline-actions">
            <button type="button" class="secondary-button" :disabled="!!busy" @click="emit('show-changelog')">更新日志</button>
            <button
              type="button"
              class="secondary-button update-check-button"
              :disabled="!!busy || !String(draft.update_manifest_url || '').trim()"
              @click="emit('check-update', String(draft.update_manifest_url || '').trim())"
            >
              {{ busy === '检查软件更新' ? busy : '检查更新' }}
            </button>
          </div>
        </div>

        <div class="settings-section">
          <h3>游戏启动增强</h3>
          <label class="switch-row">
            <input v-model="draft.custom_battle_all_units_as_lords" type="checkbox" data-testid="all-units-as-lords" />
            <span><strong>自定义战斗将所有单位视为领主</strong><small>启动时生成临时权限表，方便在自定义战斗中测试单位</small></span>
          </label>
          <label class="switch-row">
            <input v-model="draft.enable_script_logging" type="checkbox" data-testid="script-logging" />
            <span><strong>启用脚本日志</strong><small>启动时注入 script/enable_console_logging，供 MOD 脚本调试使用</small></span>
          </label>
          <label class="switch-row">
            <input v-model="draft.skip_intro_movies" type="checkbox" data-testid="skip-intro-movies" />
            <span><strong>跳过开场动画</strong><small>使用有效的空视频覆盖警告页与启动影片</small></span>
          </label>
          <small class="field-help">以上功能只在通过管理器启动游戏时生效，不会修改任何原始 MOD Pack。</small>
        </div>
      </div>

      <footer class="modal-footer">
        <button type="button" class="secondary-button" @click="emit('close')">取消</button>
        <button type="button" class="primary-button" :disabled="!!busy" @click="emit('save', { ...draft })">
          保存并重新扫描
        </button>
      </footer>
    </section>
  </div>
</template>
