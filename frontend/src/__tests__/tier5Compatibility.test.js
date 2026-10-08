import { describe, expect, it } from 'vitest'
import { tier5PackRequirement } from '../tier5Compatibility'

const marker = { id: 'marker', pack_name: 'wyccc_tier5_patch.pack', hidden: true }
const base = { id: 'base', pack_name: '!!!!!MinorTierFiveFourAll.pack' }

describe('Tier5 compatibility availability', () => {
  it('accepts an installed hidden marker without enabling it', () => {
    expect(tier5PackRequirement([marker, base], ['base']).allEnabled).toBe(true)
  })
  it('requires the base MOD to be enabled', () => {
    expect(tier5PackRequirement([marker, base], ['marker'])).toEqual({
      allEnabled: false, missing: ['MinorTierFiveFourAll'],
    })
  })
  it('requires the marker to be present', () => {
    expect(tier5PackRequirement([base], ['base']).allEnabled).toBe(false)
  })
  it('recognizes a renamed base by Workshop identity and a case-insensitive marker name', () => {
    expect(tier5PackRequirement([
      { ...marker, pack_name: 'WYCCC_TIER5_PATCH.PACK' },
      { ...base, workshop_id: '3071058075', pack_name: 'renamed.pack' },
    ], ['base']).allEnabled).toBe(true)
  })
})
