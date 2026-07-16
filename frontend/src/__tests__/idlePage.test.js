import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { describe, expect, it, vi } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const idleHtml = readFileSync(resolve(here, '../../public/idle.html'), 'utf8')

describe('low-consumption page', () => {
  it('reads the selected language from a file-safe URL fragment', () => {
    const dom = new JSDOM(idleHtml, {
      runScripts: 'dangerously',
      url: 'file:///WMM/frontend/dist/idle.html#lang=ja-JP',
    })

    expect(dom.window.document.documentElement.lang).toBe('ja')
    expect(dom.window.document.getElementById('title').textContent).toBe('ゲーム実行中')
    dom.window.close()
  })

  it('returns to the full interface instead of closing WMM', async () => {
    const call = vi.fn().mockResolvedValue({ ok: true, data: { restored: true } })
    const dom = new JSDOM(idleHtml, {
      runScripts: 'dangerously',
      url: 'file:///WMM/frontend/dist/idle.html#lang=zh-CN',
      beforeParse(window) {
        window.pywebview = { api: { call } }
      },
    })

    const button = dom.window.document.getElementById('exit')
    expect(button.textContent).toBe('退出低消耗模式')
    button.click()
    await new Promise(resolvePromise => dom.window.setTimeout(resolvePromise, 0))

    expect(call).toHaveBeenCalledOnce()
    expect(call).toHaveBeenCalledWith('exit_low_consumption_mode', [], {})
    dom.window.close()
  })

  it('never closes WMM when leaving low-consumption mode fails', async () => {
    const call = vi.fn().mockRejectedValue(new Error('bridge unavailable'))
    const close = vi.fn()
    const dom = new JSDOM(idleHtml, {
      runScripts: 'dangerously',
      url: 'file:///WMM/frontend/dist/idle.html#lang=en-US',
      beforeParse(window) {
        window.pywebview = { api: { call } }
        window.close = close
      },
    })

    dom.window.document.getElementById('exit').click()
    await new Promise(resolvePromise => dom.window.setTimeout(resolvePromise, 0))

    expect(close).not.toHaveBeenCalled()
  })
})
