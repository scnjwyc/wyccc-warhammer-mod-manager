import { createRequire } from 'node:module'
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
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

  windowsIt('ships the dependency-query build used by Workshop refresh', () => {
    const nativePath = resolve(
      process.cwd(),
      '../steam_runtime/steamworks_dependencies/dist/win64/steamworksjs.win32-x64-msvc.node',
    )
    const capabilities = execFileSync(
      process.execPath,
      [
        '-e',
        'const binding=require(process.argv[1]);process.stdout.write([typeof binding.workshop.getItemDependencies,typeof binding.workshop.getItems].join(","))',
        nativePath,
      ],
      { encoding: 'utf8' },
    )

    expect(capabilities).toBe('function,function')
  })

  it('wipes stale Workshop content and re-downloads before reporting force-update completion', () => {
    const root = mkdtempSync(join(tmpdir(), 'wmm-force-update-wipe-'))
    const bridge = join(root, 'workshop_bridge.js')
    const steamworks = join(root, 'steamworks')
    const content = join(root, 'steamapps', 'workshop', 'content', '1142710', '123')
    const backup = join(content + '.wmm-force-update-backup')
    const stalePack = join(content, 'stale.pack')
    const pack = join(content, 'new.pack')
    mkdirSync(steamworks)
    mkdirSync(content, { recursive: true })
    writeFileSync(stalePack, Buffer.alloc(3))
    copyFileSync(resolve(process.cwd(), '../steam_runtime/workshop_bridge.js'), bridge)
    writeFileSync(
      join(steamworks, 'index.js'),
      `
        "use strict";
        const fs = require("fs");
        const path = require("path");
        module.exports.init = () => ({
          workshop: {
            download: (_itemId, highPriority) => {
              if (!highPriority) throw new Error("force update was not high priority");
              setTimeout(() => {
                fs.mkdirSync(process.env.WMM_TEST_CONTENT, { recursive: true });
                fs.writeFileSync(path.join(process.env.WMM_TEST_CONTENT, "new.pack"), Buffer.alloc(10));
              }, 40);
              return true;
            },
            state: () => 5,
            installInfo: () => ({
              folder: process.env.WMM_TEST_CONTENT,
              sizeOnDisk: 10n,
              timestamp: 123,
            }),
            downloadInfo: () => ({ current: 0n, total: 10n }),
          },
        });
      `,
      'utf8',
    )

    try {
      const output = execFileSync(
        process.execPath,
        [bridge],
        {
          input: JSON.stringify({ operation: 'force_update', appId: 1142710, id: '123' }),
          encoding: 'utf8',
          timeout: 2_000,
          env: { ...process.env, WMM_TEST_CONTENT: content },
        },
      )
      const payload = JSON.parse(
        output.split('\n').find(line => line.startsWith('WMM_WORKSHOP_RESULT=')).slice(20),
      )

      expect(payload.result.completed).toBe(true)
      expect(payload.result.actual_size_on_disk).toBe('10')
      expect(readFileSync(pack).length).toBe(10)
      expect(existsSync(stalePack)).toBe(false)
      expect(existsSync(backup)).toBe(false)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('does not report force-update completion when Steam accepts but never starts a download', () => {
    const root = mkdtempSync(join(tmpdir(), 'wmm-force-update-stall-'))
    const bridge = join(root, 'workshop_bridge.js')
    const steamworks = join(root, 'steamworks')
    const content = join(root, 'steamapps', 'workshop', 'content', '1142710', '123')
    mkdirSync(steamworks)
    mkdirSync(content, { recursive: true })
    writeFileSync(join(content, 'existing.pack'), Buffer.alloc(10))
    copyFileSync(resolve(process.cwd(), '../steam_runtime/workshop_bridge.js'), bridge)
    writeFileSync(
      join(steamworks, 'index.js'),
      `
        "use strict";
        module.exports.init = () => ({
          workshop: {
            download: () => true,
            state: () => 5,
            installInfo: () => ({
              folder: process.env.WMM_TEST_CONTENT,
              sizeOnDisk: 10n,
              timestamp: 123,
            }),
            downloadInfo: () => ({ current: 0n, total: 10n }),
          },
        });
      `,
      'utf8',
    )

    try {
      let output = ''
      try {
        output = execFileSync(
          process.execPath,
          [bridge],
          {
            input: JSON.stringify({ operation: 'force_update', appId: 1142710, id: '123' }),
            encoding: 'utf8',
            timeout: 2_000,
            env: {
              ...process.env,
              WMM_TEST_CONTENT: content,
              WMM_FORCE_UPDATE_GRACE_MS: '300',
            },
          },
        )
      } catch (error) {
        output = String(error?.stdout || '')
      }
      const resultLine = output.split('\n').find(line => line.startsWith('WMM_WORKSHOP_RESULT='))
      expect(resultLine).toBeTruthy()
      const payload = JSON.parse(resultLine.slice(20))
      expect(payload.ok).toBe(false)
      expect(String(payload.error || '')).toContain('did not start downloading')
      expect(readFileSync(join(content, 'existing.pack')).length).toBe(10)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('fails and restores the original files when Steam flashes a download but delivers nothing', () => {
    const root = mkdtempSync(join(tmpdir(), 'wmm-force-update-flash-'))
    const bridge = join(root, 'workshop_bridge.js')
    const steamworks = join(root, 'steamworks')
    const content = join(root, 'steamapps', 'workshop', 'content', '1142710', '123')
    const pack = join(content, 'existing.pack')
    mkdirSync(steamworks)
    mkdirSync(content, { recursive: true })
    writeFileSync(pack, Buffer.alloc(10))
    copyFileSync(resolve(process.cwd(), '../steam_runtime/workshop_bridge.js'), bridge)
    writeFileSync(
      join(steamworks, 'index.js'),
      `
        "use strict";
        let busyPolls = 0;
        module.exports.init = () => ({
          workshop: {
            download: () => true,
            state: () => {
              busyPolls += 1;
              return busyPolls <= 3 ? 21 : 5;
            },
            installInfo: () => ({
              folder: process.env.WMM_TEST_CONTENT,
              sizeOnDisk: 10n,
              timestamp: 123,
            }),
            downloadInfo: () => ({ current: 0n, total: 10n }),
          },
        });
      `,
      'utf8',
    )

    try {
      let output = ''
      try {
        output = execFileSync(
          process.execPath,
          [bridge],
          {
            input: JSON.stringify({ operation: 'force_update', appId: 1142710, id: '123' }),
            encoding: 'utf8',
            timeout: 2_000,
            env: {
              ...process.env,
              WMM_TEST_CONTENT: content,
              WMM_FORCE_UPDATE_GRACE_MS: '300',
              WMM_FORCE_UPDATE_STALL_MS: '300',
            },
          },
        )
      } catch (error) {
        output = String(error?.stdout || '')
      }
      const resultLine = output.split('\n').find(line => line.startsWith('WMM_WORKSHOP_RESULT='))
      expect(resultLine).toBeTruthy()
      const payload = JSON.parse(resultLine.slice(20))
      expect(payload.ok).toBe(false)
      expect(String(payload.error || '')).toContain('stalled')
      expect(readFileSync(pack).length).toBe(10)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('refuses to wipe a folder that does not belong to the Workshop item', () => {
    const root = mkdtempSync(join(tmpdir(), 'wmm-force-update-guard-'))
    const bridge = join(root, 'workshop_bridge.js')
    const steamworks = join(root, 'steamworks')
    mkdirSync(steamworks)
    const sentinel = join(root, 'sentinel.txt')
    writeFileSync(sentinel, 'keep')
    copyFileSync(resolve(process.cwd(), '../steam_runtime/workshop_bridge.js'), bridge)
    writeFileSync(
      join(steamworks, 'index.js'),
      `
        "use strict";
        module.exports.init = () => ({
          workshop: {
            download: () => true,
            state: () => 5,
            installInfo: () => ({
              folder: process.env.WMM_TEST_ROOT,
              sizeOnDisk: 10n,
              timestamp: 123,
            }),
            downloadInfo: () => ({ current: 0n, total: 10n }),
          },
        });
      `,
      'utf8',
    )

    try {
      let output = ''
      try {
        output = execFileSync(
          process.execPath,
          [bridge],
          {
            input: JSON.stringify({ operation: 'force_update', appId: 1142710, id: '123' }),
            encoding: 'utf8',
            timeout: 2_000,
            env: { ...process.env, WMM_TEST_ROOT: root },
          },
        )
      } catch (error) {
        output = String(error?.stdout || '')
      }
      const resultLine = output.split('\n').find(line => line.startsWith('WMM_WORKSHOP_RESULT='))
      expect(resultLine).toBeTruthy()
      const payload = JSON.parse(resultLine.slice(20))
      expect(payload.ok).toBe(false)
      expect(String(payload.error || '')).toContain('Refusing to wipe')
      expect(readFileSync(sentinel, 'utf8')).toBe('keep')
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('subscribes a published item so the legacy CA launcher can discover it', () => {
    const root = mkdtempSync(join(tmpdir(), 'wmm-publish-subscribe-'))
    const bridge = join(root, 'workshop_bridge.js')
    const steamworks = join(root, 'steamworks')
    const content = join(root, 'content')
    const preview = join(root, 'preview.png')
    const trace = join(root, 'trace.txt')
    mkdirSync(steamworks)
    mkdirSync(content)
    writeFileSync(join(content, 'example.pack'), Buffer.alloc(3))
    writeFileSync(preview, Buffer.alloc(3))
    copyFileSync(resolve(process.cwd(), '../steam_runtime/workshop_bridge.js'), bridge)
    writeFileSync(
      join(steamworks, 'index.js'),
      `
        "use strict";
        const fs = require("fs");
        module.exports.init = () => ({
          localplayer: {
            getSteamId: () => ({ steamId64: 76561198000000000n }),
            getName: () => "Wyccc",
          },
          workshop: {
            supportsUpdateLanguage: () => true,
            getSubscribedItems: () => [],
            createItem: async () => ({
              itemId: 123n,
              needsToAcceptAgreement: false,
            }),
            updateItem: async itemId => {
              fs.appendFileSync(process.env.WMM_TEST_TRACE, \`updated:\${itemId.toString()}\\n\`);
              return { needsToAcceptAgreement: false };
            },
            subscribe: async itemId => {
              fs.appendFileSync(process.env.WMM_TEST_TRACE, \`subscribed:\${itemId.toString()}\\n\`);
            },
          },
        });
      `,
      'utf8',
    )

    try {
      let output
      try {
        output = execFileSync(
          process.execPath,
          [bridge],
          {
            input: JSON.stringify({
              operation: 'publish_item',
              appId: 1142710,
              contentPath: content,
              previewPath: preview,
              title: 'Example MOD',
              description: '',
              changeNote: '',
              tags: ['mod', 'graphical'],
              visibility: 0,
              language: 'english',
            }),
            encoding: 'utf8',
            timeout: 2_000,
            env: { ...process.env, WMM_TEST_TRACE: trace },
          },
        )
      } catch (error) {
        throw new Error(`${error.stdout || ''}${error.stderr || ''}`)
      }
      const payload = JSON.parse(
        output.split('\n').find(line => line.startsWith('WMM_WORKSHOP_RESULT=')).slice(20),
      )

      expect(payload.result.subscribed).toBe(true)
      expect(payload.result.subscription_added).toBe(true)
      expect(readFileSync(trace, 'utf8').trim().split('\n')).toEqual([
        'updated:123',
        'subscribed:123',
      ])
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})
