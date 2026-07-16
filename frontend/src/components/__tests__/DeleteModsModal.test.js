import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DeleteModsModal from '../DeleteModsModal.vue'

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
})
