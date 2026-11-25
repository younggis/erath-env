/** Visual toggles that belong to a specific data layer. */

export const BUNDLE_TOGGLES = [
  'showParticles', 'useGpuWind', 'showTrails',
  'showJet', 'showVolume', 'showTerrain',
] as const

export type BundleKey = typeof BUNDLE_TOGGLES[number]

/** Only these layers own dedicated visual controls. */
export const LAYER_BUNDLES: Record<string, readonly BundleKey[]> = {
  wind10: ['showParticles', 'useGpuWind', 'showTrails'],
  wind500: ['showJet'],
  cloud_volume: ['showVolume'],
}

export function bundleKeysFor(layerId: string): readonly BundleKey[] {
  return LAYER_BUNDLES[layerId] ?? []
}

/** Turn every bundle toggle off except the ones owned by the selected layer. */
export function transitionBundle(layerId: string): Record<BundleKey, boolean> {
  const on = new Set(bundleKeysFor(layerId))
  return Object.fromEntries(BUNDLE_TOGGLES.map(k => [k, on.has(k)])) as Record<BundleKey, boolean>
}
