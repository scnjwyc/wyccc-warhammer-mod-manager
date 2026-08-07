import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CompatibilityPatchModal from '../CompatibilityPatchModal.vue'

describe('compatibility patch modal', () => {
  it('renders the Dynamic RoRs option and defaults to the stored setting', () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        settings: { dynamic_ror_compatibility_patch_enabled: true },
      },
    })
    const checkbox = wrapper.get(
      '[data-testid="dynamic-ror-compatibility-patch-enabled"]',
    )
    expect(checkbox.element.checked).toBe(true)
    expect(wrapper.text()).toContain('Nanu')
  })

  it('disables the option and shows missing packs when a required pack is not enabled', () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        settings: {},
        requiredPacksEnabled: false,
        missingPacks: [
          "Nanu's Dynamic Regiments of Renown",
          "Nanu's Dynamic RORs Ultimate Patch",
        ],
      },
    })
    const checkbox = wrapper.get(
      '[data-testid="dynamic-ror-compatibility-patch-enabled"]',
    )
    expect(checkbox.attributes('disabled')).toBeDefined()
    const requirement = wrapper.get('[data-testid="dynamic-ror-required-packs"]')
    expect(requirement.text()).toContain("Nanu's Dynamic Regiments of Renown")
    expect(requirement.text()).toContain("Nanu's Dynamic RORs Ultimate Patch")
  })

  it('does not emit save while a required pack is missing', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        settings: {},
        requiredPacksEnabled: false,
        missingPacks: ["Nanu's Dynamic RORs Ultimate Patch"],
      },
    })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')).toBeUndefined()
  })

  it('emits the saved setting when toggled', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        settings: { dynamic_ror_compatibility_patch_enabled: false },
      },
    })
    const checkbox = wrapper.get(
      '[data-testid="dynamic-ror-compatibility-patch-enabled"]',
    )
    await checkbox.setValue(true)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('save')[0][0]).toEqual({
      dynamic_ror_compatibility_patch_enabled: true,
    })
  })

  it('emits close through the cancel button', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        settings: {},
      },
    })
    await wrapper.findAll('button').find(button => (
      button.text().includes('Cancel') || button.text().includes('取消')
    )).trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
