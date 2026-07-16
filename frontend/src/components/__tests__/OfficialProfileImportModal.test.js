import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import OfficialProfileImportModal from '../OfficialProfileImportModal.vue'

describe('OfficialProfileImportModal', () => {
  it('defaults to subscribing missing items and exposes new and replace actions', async () => {
    const wrapper = mount(OfficialProfileImportModal, {
      props: {
        open: true,
        preview: {
          profile: { name: 'Official', path: 'C:/profiles/Official.twmods' },
          references: [{ workshop_id: '123', pack_name: 'one.pack' }],
          missing: [{ workshop_id: '456', pack_name: 'missing.pack' }],
          unsubscribed: [{ workshop_id: '456', title: 'Missing', pack_name: 'missing.pack' }],
          unrecognized_lines: [],
        },
      },
    })

    expect(wrapper.get('[data-testid="official-subscribe-missing"]').element.checked).toBe(true)
    await wrapper.get('[data-testid="official-import-new"]').trigger('click')
    await wrapper.get('[data-testid="official-import-replace"]').trigger('click')

    expect(wrapper.emitted('import')[0]).toEqual([{ mode: 'new', subscribeMissing: true }])
    expect(wrapper.emitted('import')[1]).toEqual([{ mode: 'replace', subscribeMissing: true }])
  })
})
