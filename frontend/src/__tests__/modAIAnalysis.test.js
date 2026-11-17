import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('../bridge', () => ({ invoke: invokeMock }))

import App from '../App.vue'
import ModAIAnalysisModal from '../components/ModAIAnalysisModal.vue'
import { aiAnalysisEntries } from '../aiAnalysisLanguages'
import { applyInterfaceLanguage, hasTranslation, localizeBackendMessage, t } from '../languages'
import { useAppStore } from '../store'

const running = () => ({
  id: 'run-1', game_id: 'warhammer3', language: 'zh-CN', model: 'configured-model',
  status: 'running', running: true, phase: 'fetching', progress: 0,
  total_mods: 2, completed_mods: 0, current_mod: 'Sample MOD', fetched_comments: 0,
  analyzed_comments: 0, batch_current: 0, batch_total: 0, results: [], error: '',
  active_workers: 0, max_workers: 5,
})
const completed = () => ({
  ...running(), running: false, status: 'completed', phase: 'done', progress: 100, completed_mods: 2,
  fetched_comments: 3, analyzed_comments: 3,
  results: [{
    mod_ids: ['enabled'], name: 'Sample MOD', workshop_id: '123', status: 'issues', error: '',
    url: 'https://steamcommunity.com/sharedfiles/filedetails/?id=123',
    updated_at: 1000000, comment_count: 3, analyzed_count: 3, issue_count: 1,
    summary: '玩家报告加载崩溃。', comments: [
      { id: '1', author: 'Player', posted_at: 1100000, text: 'Crash on load', translation: '加载时崩溃',
        category: 'issue', is_issue: true, summary: '加载崩溃', url: 'https://steamcommunity.com/sharedfiles/filedetails/?id=123#comment_1' },
      { id: '2', author: 'Other player', posted_at: 1200000, text: 'Works fine', translation: '运行正常',
        category: 'positive', is_issue: false, summary: '', url: 'https://steamcommunity.com/sharedfiles/filedetails/?id=123#comment_2' },
      { id: '3', author: 'Question player', posted_at: 1300000, text: 'Is PLACEHOLD normal?', translation: '派系名显示PLACEHOLD是正常的吗？',
        category: 'question', is_issue: true, summary: '询问是否正常', url: 'https://steamcommunity.com/sharedfiles/filedetails/?id=123#comment_3' },
    ],
  }, { mod_ids: ['local'], name: 'Local MOD', workshop_id: '', url: '', status: 'skipped', error: '',
    updated_at: 0, comment_count: 0, analyzed_count: 0, issue_count: 0, summary: '', comments: [] }],
})

describe('enabled MOD Workshop AI analysis', () => {
  let pinia, store, wrapper
  beforeEach(() => {
    vi.useFakeTimers()
    pinia = createPinia()
    setActivePinia(pinia)
    store = useAppStore()
    store.settings = { selected_game: 'warhammer3', language: 'zh-CN', ai_enabled: true,
      ai_model: 'configured-model', ai_base_url: 'https://example.invalid/v1' }
    store.pathHealth = { game_ready: true, workshop_path_exists: true }
    store.mods = ['enabled', 'local', 'disabled'].map(id => ({ id, pack_name: `${id}.pack`, effective_name: id,
      display_name: id, source: 'data', warnings: [], mod_type: 'unknown', mod_types: ['unknown'] }))
    store.replaceActiveIds(['enabled', 'local'])
    vi.spyOn(store, 'bootstrap').mockResolvedValue({})
    invokeMock.mockReset()
    invokeMock.mockImplementation(async method => {
      if (method === 'start_mod_ai_analysis') return running()
      if (method === 'get_mod_ai_analysis') return completed()
      if (method === 'cancel_mod_ai_analysis') return { ...running(), phase: 'cancelling' }
      if (method === 'get_diagnostics_history') return []
      return {}
    })
  })
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  const openModal = async () => {
    wrapper = mount(ModAIAnalysisModal, { props: { open: false }, global: { plugins: [pinia] } })
    await wrapper.setProps({ open: true })
    await flushPromises()
  }

  it('keeps AI analysis in the footer and starts with all enabled IDs', async () => {
    wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.find('[data-testid="sync-data-button"]').exists()).toBe(false)
    expect(wrapper.get('.footer-left').find('[data-testid="mod-diagnostics-button"]').exists()).toBe(false)
    expect(wrapper.get('.footer-analysis-actions').findAll('button').map(button => button.attributes('data-testid')))
      .toEqual(['ai-analysis-button'])
    store.activeSearch = 'does not match'
    await wrapper.get('[data-testid="ai-analysis-button"]').trigger('click')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('start_mod_ai_analysis', ['enabled', 'local'])
    expect(wrapper.get('[data-testid="ai-analysis-modal"]').text()).toContain('configured-model')
    expect(wrapper.get('progress').attributes('value')).toBe('0')
    expect(wrapper.get('[data-testid="ai-analysis-cancel"]').exists()).toBe(true)
  })

  it('polls progress and displays MOD conclusions and issue reports without an overall summary', async () => {
    invokeMock.mockImplementation(async method => {
      if (method === 'start_mod_ai_analysis') return running()
      if (method === 'get_mod_ai_analysis') return { ...completed(), summary: '不应展示旧整体汇总', summary_error: 'aiAnalysis.aiFailed' }
      return {}
    })
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('get_mod_ai_analysis', 'run-1')
    expect(wrapper.get('progress').attributes('value')).toBe('100')
    expect(wrapper.find('[data-testid="ai-analysis-summary"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('整体汇总')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="ai-analysis-conclusion"]').text()).toContain('玩家报告加载崩溃')
    expect(wrapper.findAll('[data-testid="ai-analysis-translation"]').map(item => item.text())).toEqual(['加载时崩溃'])
    expect(wrapper.get('.ai-analysis-original').text()).toContain('Crash on load')
    expect(wrapper.find('[data-status="skipped"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ai-analysis-all-comments"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Local MOD')
    expect(wrapper.text()).not.toContain('运行正常')
    expect(wrapper.text()).not.toContain('PLACEHOLD')
    await wrapper.findAll('.ai-analysis-comment button')[0].trigger('click')
    expect(invokeMock).toHaveBeenCalledWith('open_external_url', completed().results[0].comments[0].url)
    await vi.advanceTimersByTimeAsync(5000)
    expect(invokeMock.mock.calls.filter(([method]) => method === 'get_mod_ai_analysis')).toHaveLength(1)
  })

  it('omits MODs with no issue reports even when they have positive comments or summaries', async () => {
    const state = completed()
    state.results = [
      { ...state.results[0], name: 'No issue MOD', status: 'clean', issue_count: 0,
        summary: '一切正常，谢谢作者', comments: [state.results[0].comments[1]] },
      { ...state.results[1], name: 'No new comments MOD', status: 'no_comments' },
      state.results[1],
    ]
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis' ? running() : state)
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.findAll('.ai-analysis-result')).toHaveLength(0)
    expect(wrapper.find('[data-testid="ai-analysis-summary"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ai-analysis-all-comments"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('No issue MOD')
    expect(wrapper.text()).not.toContain('No new comments MOD')
    expect(wrapper.text()).not.toContain('Local MOD')
    expect(wrapper.text()).not.toContain('谢谢作者')
  })

  it('keeps request failures visible without creating empty MOD result cards', async () => {
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis' ? running() : {
      ...completed(), status: 'partial',
      results: [{ ...completed().results[1], name: 'Failed MOD', status: 'error', error: 'aiAnalysis.workshopFailed' }],
    })
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.findAll('.ai-analysis-result')).toHaveLength(0)
    expect(wrapper.text()).toContain('Failed MOD')
    expect(wrapper.text()).toContain('无法读取工坊数据')
  })

  it('allows stopping and keeps the dialog open until the current request finishes', async () => {
    await openModal()
    expect(wrapper.findAll('.icon-button')[0].attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="ai-analysis-cancel"]').trigger('click')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('cancel_mod_ai_analysis', 'run-1')
    expect(wrapper.text()).toContain('等待当前请求结束')
    expect(wrapper.get('[data-testid="ai-analysis-cancel"]').attributes('disabled')).toBeDefined()
    invokeMock.mockImplementation(async () => ({ ...running(), status: 'cancelled', phase: 'done', running: false }))
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await wrapper.get('.icon-button').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('shows five concurrent AI agents and updates the active count from progress polling', async () => {
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis'
      ? { ...running(), phase: 'analyzing', active_workers: 5 }
      : { ...running(), phase: 'mod_summary', active_workers: 2 })
    await openModal()
    expect(wrapper.get('[data-testid="ai-analysis-workers"]').text()).toContain('5 / 5')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.get('[data-testid="ai-analysis-workers"]').text()).toContain('2 / 5')
  })

  it('shows AI settings guidance without issuing requests when AI is not configured', async () => {
    store.settings.ai_enabled = false
    await openModal()
    expect(invokeMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请先在设置中启用AI')
    expect(wrapper.get('[data-testid="ai-analysis-start"]').attributes('disabled')).toBeDefined()
    await wrapper.findAll('footer button')[0].trigger('click')
    expect(wrapper.emitted('settings')).toHaveLength(1)
  })

  it('retains polling after a temporary bridge error and never reports completion prematurely', async () => {
    await openModal()
    invokeMock.mockRejectedValueOnce(new Error('temporary bridge error'))
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('temporary bridge error')
    expect(wrapper.get('progress').attributes('value')).toBe('0')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('progress').attributes('value')).toBe('100')
  })

  it('cancels stale in-flight starts when the game context changes', async () => {
    let finishStart
    invokeMock.mockImplementation(method => method === 'start_mod_ai_analysis'
      ? new Promise(resolve => { finishStart = resolve }) : Promise.resolve({}))
    await openModal()
    store.gameContextRevision += 1
    await flushPromises()
    finishStart(running())
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('cancel_mod_ai_analysis', 'run-1')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.find('progress').exists()).toBe(false)
  })

  it('retains issue reports from partial analyses and shows their failures', async () => {
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis' ? running() : {
      ...completed(), status: 'partial',
      results: [{ ...completed().results[0], status: 'error', error: 'aiAnalysis.incompleteComments' }],
    })
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.text()).toContain('部分内容未能分析')
    expect(wrapper.get('[data-status="error"]').text()).toContain('工坊分页未返回完整评论')
    expect(wrapper.find('[data-testid="ai-analysis-summary"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="ai-analysis-translation"]').text()).toContain('加载时崩溃')
  })

  it('paginates MOD results and searches their names, Pack filenames and Workshop IDs without querying AI again', async () => {
    const state = completed()
    const sample = state.results[0]
    state.results = Array.from({ length: 12 }, (_, index) => ({ ...sample, mod_ids: [`mod-${index}`],
      name: `MOD ${index + 1}`, pack_names: [`special_${index + 1}.pack`], workshop_id: String(1000 + index) }))
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis' ? running() : state)
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.findAll('.ai-analysis-mod-title').map(item => item.text())).toEqual(['MOD 1', 'MOD 2', 'MOD 3', 'MOD 4', 'MOD 5'])
    expect(wrapper.get('[data-testid="ai-analysis-page-info"]').text()).toContain('1 / 3')
    expect(wrapper.get('[data-testid="ai-analysis-prev"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="ai-analysis-next"]').trigger('click')
    expect(wrapper.findAll('.ai-analysis-mod-title')[0].text()).toBe('MOD 6')
    await wrapper.get('[data-testid="ai-analysis-next"]').trigger('click')
    expect(wrapper.findAll('.ai-analysis-result')).toHaveLength(2)
    expect(wrapper.get('[data-testid="ai-analysis-next"]').attributes('disabled')).toBeDefined()
    for (const query of ['mod 12', 'special_12.pack', '1011']) {
      await wrapper.get('[data-testid="ai-analysis-search"]').setValue(query)
      expect(wrapper.findAll('.ai-analysis-mod-title').map(item => item.text())).toEqual(['MOD 12'])
      expect(wrapper.get('[data-testid="ai-analysis-page-info"]').text()).toContain('1 / 1')
    }
    await wrapper.get('[data-testid="ai-analysis-search"]').setValue('不存在的 MOD')
    expect(wrapper.findAll('.ai-analysis-result')).toHaveLength(0)
    expect(wrapper.get('[data-testid="ai-analysis-no-matches"]').text()).toContain('没有匹配')
    await wrapper.get('[data-testid="ai-analysis-search"]').setValue('')
    expect(wrapper.findAll('.ai-analysis-result')).toHaveLength(5)
    expect(invokeMock.mock.calls.filter(([method]) => method === 'start_mod_ai_analysis')).toHaveLength(1)
  })

  it('keeps a MOD conclusion collapsed across polling and page changes', async () => {
    const state = { ...completed(), running: true, status: 'running' }
    const sample = state.results[0]
    state.results = Array.from({ length: 6 }, (_, index) => ({ ...sample, mod_ids: [`mod-${index}`], name: `MOD ${index}` }))
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis' ? running() : state)
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    const conclusion = wrapper.findAll('[data-testid="ai-analysis-conclusion"]')[0]
    conclusion.element.open = false
    await conclusion.trigger('toggle')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.findAll('[data-testid="ai-analysis-conclusion"]')[0].element.open).toBe(false)
    await wrapper.get('[data-testid="ai-analysis-next"]').trigger('click')
    await wrapper.get('[data-testid="ai-analysis-prev"]').trigger('click')
    expect(wrapper.findAll('[data-testid="ai-analysis-conclusion"]')[0].element.open).toBe(false)
  })

  it('paginates long MOD comment evidence', async () => {
    const state = completed()
    const sample = state.results[0]
    sample.comments = Array.from({ length: 23 }, (_, index) => ({ ...sample.comments[0], id: String(index), translation: `异常评论 ${index + 1}` }))
    sample.issue_count = 23
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis' ? running() : state)
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.findAll('.ai-analysis-comment')).toHaveLength(10)
    expect(wrapper.get('[data-testid="ai-analysis-comment-prev"]').attributes('disabled')).toBeDefined()
    const scrollToComments = vi.fn()
    wrapper.get('.ai-analysis-comments').element.scrollIntoView = scrollToComments
    await wrapper.get('[data-testid="ai-analysis-comment-next"]').trigger('click')
    expect(scrollToComments).toHaveBeenCalledWith({ block: 'start' })
    expect(wrapper.findAll('[data-testid="ai-analysis-translation"]')[0].text()).toBe('异常评论 11')
    await wrapper.get('[data-testid="ai-analysis-comment-next"]').trigger('click')
    expect(wrapper.findAll('.ai-analysis-comment')).toHaveLength(3)
    expect(wrapper.get('[data-testid="ai-analysis-comment-next"]').attributes('disabled')).toBeDefined()
  })

  it('shows cache capacity and reused analysis counts', async () => {
    invokeMock.mockImplementation(async method => method === 'start_mod_ai_analysis' ? running() : {
      ...completed(), cache_bytes: 1024 * 1024 * 12, cached_comments: 3, cached_summaries: 2,
    })
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.get('[data-testid="ai-analysis-cache-info"]').text()).toContain('12.0 / 100 MB')
    expect(wrapper.get('[data-testid="ai-analysis-cache-hits"]').text()).toContain('评论 3 条 · 总结 2 次')
  })

  it('provides every UI and backend error key in all six interface languages', () => {
    for (const key of Object.keys(aiAnalysisEntries)) expect(hasTranslation(key), key).toBe(true)
    for (const language of ['zh-CN', 'en-US', 'ko-KR', 'ru-RU', 'ja-JP', 'es-ES']) {
      applyInterfaceLanguage(language)
      expect(localizeBackendMessage('aiAnalysis.configureAI')).toBe(t('aiAnalysis.configureAI'))
      expect(t('aiAnalysis.title')).not.toBe('aiAnalysis.title')
    }
  })

  it('starts a fresh analysis of the current enabled MODs when reopened', async () => {
    await openModal()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await wrapper.setProps({ open: false })
    store.replaceActiveIds(['disabled'])
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(invokeMock).toHaveBeenLastCalledWith('start_mod_ai_analysis', ['disabled'])
    expect(wrapper.get('progress').attributes('value')).toBe('0')
  })

  it('clears and cancels the previous-language run when the interface language changes', async () => {
    await openModal()
    store.settings.language = 'en-US'
    applyInterfaceLanguage('en-US')
    await flushPromises()
    expect(invokeMock).toHaveBeenCalledWith('cancel_mod_ai_analysis', 'run-1')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.find('progress').exists()).toBe(false)
    expect(wrapper.text()).toContain('AI analysis')
  })
})
