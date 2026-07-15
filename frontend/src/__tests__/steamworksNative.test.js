import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const windowsIt = process.platform === 'win32' ? it : it.skip

describe('bundled Steamworks native bridge', () => {
  windowsIt('loads through N-API and advertises localized update support', () => {
    const nativePath = resolve(
      process.cwd(),
      '../steam_runtime/steamworks/dist/win64/steamworksjs.win32-x64-msvc.node',
    )
    const binding = createRequire(import.meta.url)(nativePath)

    expect(binding.workshop.supportsUpdateLanguage()).toBe(true)
    expect(typeof binding.workshop.subscribe).toBe('function')
    expect(typeof binding.workshop.getSubscribedItems).toBe('function')
  })
})
