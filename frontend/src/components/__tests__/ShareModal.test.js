import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ShareModal from '../ShareModal.vue'

describe('share modal JSON playset', () => {
  it('emits export-json with the description option', async () => {
    const wrapper = mount(ShareModal, { props: { open: true } })
    await wrapper.get('[data-testid="share-export-json"]').trigger('click')
    expect(wrapper.emitted('export-json')[0]).toEqual([false])
    await wrapper.get('.share-json-check input').setValue(true)
    await wrapper.get('[data-testid="share-export-json"]').trigger('click')
    expect(wrapper.emitted('export-json')[1]).toEqual([true])
  })

  it('emits import-json with the selected mode', async () => {
    const wrapper = mount(ShareModal, { props: { open: true } })
    await wrapper.get('[data-testid="share-import-json"]').trigger('click')
    expect(wrapper.emitted('import-json')[0]).toEqual(['new'])
    await wrapper.get('.share-json-mode select').setValue('current')
    await wrapper.get('[data-testid="share-import-json"]').trigger('click')
    expect(wrapper.emitted('import-json')[1]).toEqual(['current'])
  })
})
