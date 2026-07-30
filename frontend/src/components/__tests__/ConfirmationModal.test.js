import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ConfirmationModal from '../ConfirmationModal.vue'

describe('ConfirmationModal', () => {
  it('renders a themed centered confirmation with cancel and destructive actions', async () => {
    const wrapper = mount(ConfirmationModal, {
      props: {
        open: true,
        message: 'This action cannot be undone.',
        confirmLabel: 'Delete',
        danger: true,
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('[role="alertdialog"]').classes()).toContain('confirmation-modal')
    expect(wrapper.get('[data-testid="confirmation-confirm"]').classes()).toContain('danger-button')
    expect(wrapper.text()).toContain('This action cannot be undone.')

    await wrapper.get('[data-testid="confirmation-confirm"]').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    await wrapper.get('.secondary-button').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
