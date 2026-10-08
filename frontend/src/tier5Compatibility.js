// Presence unlocks the feature marker; the base MOD must be enabled.
export const tier5PackRequirement = (mods, activeIds) => {
  const active = new Set(activeIds)
  const installed = mods.some(mod => (
    String(mod.pack_name || '').toLowerCase() === 'wyccc_tier5_patch.pack'
  ))
  const baseEnabled = mods.some(mod => (
    active.has(mod.id)
    && (String(mod.workshop_id || '') === '3071058075'
      || String(mod.pack_name || '').toLowerCase().replace(/^!+/, '') === 'minortierfivefourall.pack')
  ))
  const missing = []
  if (!installed) missing.push('wyccc_tier5_patch.pack')
  if (!baseEnabled) missing.push('MinorTierFiveFourAll')
  return { allEnabled: installed && baseEnabled, missing }
}
