import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DeleteModsModal from '../DeleteModsModal.vue'

const stylesSource = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8')

describe('DeleteModsModal', () => {
  it('shows source counts and full paths before confirmation', async () => {
    const wrapper = mount(DeleteModsModal, {
      props: {
        open: true,
        preview: {
          token: 'preview-token',
          data_count: 1,
          workshop_count: 1,
          targets: [
            { source: 'data', path: 'X:/game/data/one.pack', pack_name: 'one.pack' },
            { source: 'workshop', path: 'X:/workshop/123/two.pack', pack_name: 'two.pack' },
          ],
        },
      },
    })

    expect(wrapper.text()).toContain('X:/game/data/one.pack')
    expect(wrapper.text()).toContain('X:/workshop/123/two.pack')
    await wrapper.get('[data-testid="confirm-delete-mods"]').trigger('click')
    expect(wrapper.emitted('confirm')[0]).toEqual(['preview-token'])
  })

  it('gives the recycle confirmation a dedicated destructive button treatment', () => {
    const wrapper = mount(DeleteModsModal, {
      props: {
        open: true,
        preview: { token: 'preview-token', data_count: 1, workshop_count: 0, targets: [] },
      },
    })
    const confirm = wrapper.get('[data-testid="confirm-delete-mods"]')

    expect(confirm.classes()).toContain('danger-button')
    expect(stylesSource).toMatch(
      /\.danger-button\s*\{[^}]*border-color:[^}]*background:[^}]*color:/s,
    )
    expect(stylesSource).toMatch(/\.danger-button:hover:not\(:disabled\)\s*\{[^}]*background/s)
  })
})
