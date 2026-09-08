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
          "Nanu's Dynamic RORs Ultimate Compatibility Patch",
        ],
      },
    })
    const checkbox = wrapper.get(
      '[data-testid="dynamic-ror-compatibility-patch-enabled"]',
    )
    expect(checkbox.attributes('disabled')).toBeDefined()
    const requirement = wrapper.get('[data-testid="dynamic-ror-required-packs"]')
    expect(requirement.text()).toContain("Nanu's Dynamic Regiments of Renown")
    expect(requirement.text()).toContain("Nanu's Dynamic RORs Ultimate Compatibility Patch")
  })

  it('forces stored options off when their dependencies are missing', () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        settings: {
          dynamic_ror_compatibility_patch_enabled: true,
          variant_selector_compatibility_patch_enabled: true,
        },
        requiredPacksEnabled: false,
        variantSelectorPacksEnabled: false,
      },
    })
    const dynamicRorCheckbox = wrapper.get(
      '[data-testid="dynamic-ror-compatibility-patch-enabled"]',
    )
    const variantSelectorCheckbox = wrapper.get(
      '[data-testid="variant-selector-compatibility-patch-enabled"]',
    )

    expect(dynamicRorCheckbox.element.checked).toBe(false)
    expect(dynamicRorCheckbox.attributes('disabled')).toBeDefined()
    expect(variantSelectorCheckbox.element.checked).toBe(false)
    expect(variantSelectorCheckbox.attributes('disabled')).toBeDefined()
  })

  it('saves both options off while dependencies are missing', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        settings: {},
        requiredPacksEnabled: false,
        missingPacks: ["Nanu's Dynamic RORs Ultimate Compatibility Patch"],
      },
    })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')[0][0]).toEqual({
      dynamic_ror_compatibility_patch_enabled: false,
      variant_selector_compatibility_patch_enabled: false,
    })
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
      variant_selector_compatibility_patch_enabled: false,
    })
  })

  it('enables Variant Selector by default when available', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        requiredPacksEnabled: false,
        variantSelectorPacksEnabled: true,
        settings: {},
      },
    })
    const checkbox = wrapper.get('[data-testid="variant-selector-compatibility-patch-enabled"]')
    expect(checkbox.element.checked).toBe(true)
    expect(checkbox.attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('Dynamic Variant Selector Patch')
    await checkbox.setValue(false)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')[0][0]).toEqual({
      dynamic_ror_compatibility_patch_enabled: false,
      variant_selector_compatibility_patch_enabled: false,
    })
  })

  it('clears a stored preference when Variant Selector dependencies are missing', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        variantSelectorPacksEnabled: false,
        variantSelectorMissingPacks: ['Dynamic Variant Selector Patch', 'Variant Selector'],
        settings: { variant_selector_compatibility_patch_enabled: true },
      },
    })
    const checkbox = wrapper.get('[data-testid="variant-selector-compatibility-patch-enabled"]')
    const requirement = wrapper.get('[data-testid="variant-selector-required-packs"]')
    expect(requirement.text()).toContain('Dynamic Variant Selector Patch')
    expect(checkbox.attributes('disabled')).toBeDefined()
    expect(checkbox.element.checked).toBe(false)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')[0][0].variant_selector_compatibility_patch_enabled).toBe(false)
  })

  it('turns an open option off when its dependency disappears', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: {
        open: true,
        variantSelectorPacksEnabled: true,
        settings: { variant_selector_compatibility_patch_enabled: true },
      },
    })
    const checkbox = wrapper.get('[data-testid="variant-selector-compatibility-patch-enabled"]')
    expect(checkbox.element.checked).toBe(true)

    await wrapper.setProps({ variantSelectorPacksEnabled: false })

    expect(checkbox.element.checked).toBe(false)
    expect(checkbox.attributes('disabled')).toBeDefined()
  })

  it('does not save while busy', async () => {
    const wrapper = mount(CompatibilityPatchModal, {
      props: { open: true, busy: 'Saving' },
    })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')).toBeUndefined()
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
