import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SaveModsComparisonModal from '../SaveModsComparisonModal.vue'

describe('SaveModsComparisonModal', () => {
  it('renders all three comparison groups and their counts', () => {
    const wrapper = mount(SaveModsComparisonModal, {
      props: {
        open: true,
        comparison: {
          save: { name: 'campaign.save' },
          saveOnly: [{ packName: 'missing.pack', mod: null }],
          currentOnly: [{ packName: 'extra.pack', mod: { effective_name: 'Extra' } }],
          shared: [{ packName: 'same.pack', mod: { effective_name: 'Same' } }],
        },
      },
    })

    expect(wrapper.get('[data-testid="save-only-group"] h3').text()).toContain('1')
    expect(wrapper.get('[data-testid="current-only-group"]').text()).toContain('Extra')
    expect(wrapper.get('[data-testid="shared-group"]').text()).toContain('Same')
  })
})
