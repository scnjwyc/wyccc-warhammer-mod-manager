import { readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(here, '../..')
const repositoryRoot = resolve(frontendRoot, '..')

const read = path => readFileSync(path, 'utf8')

describe('deliberately small product scope', () => {
  it('does not expose removed feature modules from the main UI', () => {
    const appSource = read(resolve(frontendRoot, 'src/App.vue'))
    const forbiddenComponents = [
      'ModGroups',
      'DependencyGraph',
      'RuleCenter',
      'TextureOptimizer',
      'FileContentSearch',
      'ModSettings',
      'LogAnalysis',
    ]

    for (const component of forbiddenComponents) {
      expect(appSource).not.toContain(component)
    }

    const componentNames = readdirSync(resolve(frontendRoot, 'src/components'))
    for (const component of forbiddenComponents) {
      expect(componentNames).not.toContain(`${component}.vue`)
    }
  })

  it('keeps language support and file statistics out of the detail source', () => {
    const detailsSource = read(resolve(frontendRoot, 'src/components/ModDetails.vue'))
    for (const marker of ['支持语言', '文件统计', 'supported_languages', 'file_stats']) {
      expect(detailsSource).not.toContain(marker)
    }
  })

  it('keeps the detail preview at 70 percent of its width and center-cropped', () => {
    const stylesSource = read(resolve(frontendRoot, 'src/styles.css'))
    expect(stylesSource).toMatch(/\.details-visual\s*\{[^}]*aspect-ratio:\s*10\s*\/\s*7/s)
    expect(stylesSource).toMatch(/\.details-visual img\s*\{[^}]*object-position:\s*center center/s)
    expect(stylesSource).not.toContain('flex: 0 0 444px')
    expect(stylesSource).not.toContain('flex-basis: 350px')
  })

  it('allows native text selection for the mod name and pack filename', () => {
    const stylesSource = read(resolve(frontendRoot, 'src/styles.css'))

    expect(stylesSource).toMatch(/\.selectable-detail-text\s*\{[^}]*-webkit-user-select:\s*text/s)
    expect(stylesSource).toMatch(/\.selectable-detail-text\s*\{[^}]*user-select:\s*text/s)
  })

  it('doubles the expanded Workshop description viewport height', () => {
    const stylesSource = read(resolve(frontendRoot, 'src/styles.css'))
    expect(stylesSource).toMatch(/\.description-text\s*\{[^}]*max-height:\s*360px/s)
  })

  it('does not register removed backend RPC entry points', () => {
    const apiSource = read(resolve(repositoryRoot, 'backend/api.py'))
    const forbiddenRpcNames = [
      'groups',
      'dependency_graph',
      'rules',
      'texture_optimization',
      'file_content_search',
      'mod_settings',
      'log_analysis',
    ]

    for (const method of forbiddenRpcNames) {
      expect(apiSource).not.toMatch(new RegExp(`["']${method}["']\\s*:`))
    }
  })

  it('uses a persistent playset model instead of preset snapshots', () => {
    const appSource = read(resolve(frontendRoot, 'src/App.vue'))
    const shareSource = read(resolve(frontendRoot, 'src/components/ShareModal.vue'))
    const storeSource = read(resolve(frontendRoot, 'src/store.js'))
    const apiSource = read(resolve(repositoryRoot, 'backend/api.py'))

    expect(appSource).toContain("t('app.playset')")
    expect(appSource).toContain("t('app.newPlayset')")
    expect(appSource).not.toContain('当前加载顺序')
    expect(appSource).not.toContain('另存预设')
    expect(shareSource).toContain("t('share.importCurrent')")
    expect(shareSource).not.toContain('导入到当前列表')
    expect(storeSource).toContain("invoke('update_playset'")
    expect(storeSource).toContain("invoke('save_load_order'")
    expect(appSource).not.toContain('保存加载顺序')
    expect(apiSource).toContain('"switch_playset"')
    expect(apiSource).not.toContain('"apply_preset"')
  })

  it('uses fixed Data and Workshop scanning without RPFM path configuration', () => {
    const settingsSource = read(resolve(frontendRoot, 'src/components/SettingsModal.vue'))
    const backendSettings = read(resolve(repositoryRoot, 'backend/app_settings.py'))
    const scannerSource = read(resolve(repositoryRoot, 'backend/scanner.py'))

    for (const removed of ['rpfm_path', 'scan_modding', 'scan_merged']) {
      expect(settingsSource).not.toContain(removed)
      expect(backendSettings).not.toContain(`"${removed}"`)
      expect(scannerSource).not.toContain(`settings.get("${removed}")`)
    }
    expect(settingsSource).not.toContain('scan_modding')
    expect(settingsSource).toContain("t('settings.scanScope')")
  })

  it('keeps the playset label clear of the themed select border', () => {
    const stylesSource = read(resolve(frontendRoot, 'src/styles.css'))

    expect(stylesSource).toMatch(/\.playset-select\s*\{[^}]*gap:\s*10px/s)
    expect(stylesSource).toMatch(/\.playset-select > span\s*\{[^}]*white-space:\s*nowrap/s)
    expect(stylesSource).toMatch(/\.playset-select \.themed-select\s*\{[^}]*width:\s*174px/s)
  })

  it('replaces native select popups with the shared themed dropdown', () => {
    for (const relativePath of [
      'src/App.vue',
      'src/components/SettingsModal.vue',
      'src/components/WorkshopPublishModal.vue',
    ]) {
      const source = read(resolve(frontendRoot, relativePath))
      expect(source).not.toMatch(/<select\b/)
      expect(source).toContain('ThemedSelect')
    }
  })

  it('uses a larger readable type scale for settings tabs and changelog entries', () => {
    const stylesSource = read(resolve(frontendRoot, 'src/styles.css'))

    expect(stylesSource).toMatch(/\.settings-tab-copy strong\s*\{[^}]*font-size:\s*16px/s)
    expect(stylesSource).toMatch(/\.settings-tab-copy small\s*\{[^}]*font-size:\s*13px/s)
    expect(stylesSource).toMatch(/\.details-meta dt\s*\{[^}]*font-size:\s*11px/s)
    expect(stylesSource).toMatch(/\.details-meta dd\s*\{[^}]*font-size:\s*12px/s)
    expect(stylesSource).toMatch(/\.continue-button,\s*\n\.launch-button\s*\{[^}]*font-size:\s*14px/s)
    expect(stylesSource).toMatch(/\.type-manager-help\s*\{[^}]*font-size:\s*13px/s)
    expect(stylesSource).toMatch(/\.type-name-readonly\s*\{[^}]*font-size:\s*14px/s)
    expect(stylesSource).toMatch(/\.release-entry > header strong\s*\{[^}]*font-size:\s*19px/s)
    expect(stylesSource).toMatch(/\.release-entry > header time\s*\{[^}]*font-size:\s*13px/s)
    expect(stylesSource).not.toContain('.change-entry h3')
    expect(stylesSource).toMatch(/\.change-list\s*\{[^}]*gap:\s*8px/s)
    expect(stylesSource).toMatch(/\.change-list li\s*\{[^}]*font-size:\s*14px/s)
  })

  it('uses fixed header, content, and footer rows for every settings tab', () => {
    const stylesSource = read(resolve(frontendRoot, 'src/styles.css'))

    expect(stylesSource).toMatch(/\.settings-modal\s*\{[^}]*display:\s*grid[^}]*grid-template-rows:\s*68px\s+minmax\(0,\s*1fr\)\s+62px/s)
    expect(stylesSource).toMatch(/\.settings-layout\s*\{[^}]*height:\s*100%[^}]*min-height:\s*0/s)
    expect(stylesSource).toMatch(/\.settings-page-scroll\s*\{[^}]*min-height:\s*0[^}]*overflow-y:\s*auto/s)
  })

  it('centers the warning entry in the enabled-list heading instead of using a bottom strip', () => {
    const appSource = read(resolve(frontendRoot, 'src/App.vue'))
    const stylesSource = read(resolve(frontendRoot, 'src/styles.css'))

    expect(appSource).toContain(':warning-count="store.warningCount"')
    expect(appSource).toContain('@show-warnings="showWarnings = true"')
    expect(appSource).toContain('<WarningModal')
    expect(appSource).not.toContain('class="warning-area"')
    expect(stylesSource).toMatch(/\.panel-warning-button\s*\{[^}]*left:\s*50%[^}]*transform:\s*translateX\(-50%\)/s)
  })

  it('exposes game data modification from the left footer', () => {
    const appSource = read(resolve(frontendRoot, 'src/App.vue'))

    expect(appSource).toContain("import GameDataModificationModal")
    expect(appSource).toContain('data-testid="game-data-modification-button"')
    expect(appSource).toContain("t('app.gameDataModification')")
    expect(appSource).toContain('<GameDataModificationModal')
    expect(appSource).not.toContain('gameDataGeneratedSignature')
    expect(appSource).not.toContain('@generate=')
  })

  it('opens game data modification before refreshing Steam subscription status', () => {
    const appSource = read(resolve(frontendRoot, 'src/App.vue'))
    const start = appSource.indexOf('const openGameDataModification')
    const end = appSource.indexOf('\n}', start)
    const handler = appSource.slice(start, end)

    expect(start).toBeGreaterThan(-1)
    expect(handler.indexOf('showGameDataModification.value = true')).toBeGreaterThan(-1)
    expect(handler.indexOf('store.refreshGameDataFeatures()')).toBeGreaterThan(-1)
    expect(handler.indexOf('showGameDataModification.value = true'))
      .toBeLessThan(handler.indexOf('store.refreshGameDataFeatures()'))
    expect(handler).not.toContain('await store.refreshGameDataFeatures()')
  })

  it('routes separate browser and Steam-client Workshop actions', () => {
    const appSource = read(resolve(frontendRoot, 'src/App.vue'))
    const storeSource = read(resolve(frontendRoot, 'src/store.js'))

    expect(appSource).toContain("action === 'open-workshop-browser'")
    expect(appSource).toContain("action === 'open-workshop-client'")
    expect(storeSource).toContain("invoke('open_workshop_page', modId)")
    expect(storeSource).toContain("invoke('open_workshop_client', modId)")
  })
})
