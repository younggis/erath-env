import { describe, expect, it } from 'vitest'
import { BUNDLE_TOGGLES, bundleKeysFor, transitionBundle } from './layerBundles'

describe('layer bundles', () => {
  it('binds wind particles to the wind layer', () => {
    expect(bundleKeysFor('wind10')).toEqual(['showParticles', 'useGpuWind', 'showTrails'])
    const next = transitionBundle('wind10')
    expect(next.showParticles).toBe(true)
    expect(next.useGpuWind).toBe(true)
    expect(next.showTrails).toBe(true)
    expect(next.showJet).toBe(false)
    expect(next.showVolume).toBe(false)
  })

  it('turns all bundle toggles off for layers without dedicated effects', () => {
    const next = transitionBundle('temp2m')
    expect(BUNDLE_TOGGLES.every(k => next[k] === false)).toBe(true)
  })

  it('switches effects when moving between bundled layers', () => {
    const jet = transitionBundle('wind500')
    expect(jet.showJet).toBe(true)
    expect(jet.showParticles).toBe(false)
    const cloud = transitionBundle('cloud_volume')
    expect(cloud.showVolume).toBe(true)
    expect(cloud.showJet).toBe(false)
  })
})
