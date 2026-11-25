import { describe, expect, it } from 'vitest'
import { coneScale, eruptionRecency, pulseFrequency, volcanoRadius } from './volcanoGlow'

describe('volcano glow helpers', () => {
  it('maps eruption recency into 0..1', () => {
    expect(eruptionRecency(null)).toBeCloseTo(0.15)
    expect(eruptionRecency(-7000)).toBeCloseTo(0)
    expect(eruptionRecency(2026)).toBeCloseTo(1)
    expect(eruptionRecency(1600)).toBeGreaterThan(0.9)
    const r = eruptionRecency(1600)
    expect(r).toBeGreaterThan(0)
    expect(r).toBeLessThanOrEqual(1)
  })

  it('pulses recent volcanoes faster', () => {
    expect(pulseFrequency(1)).toBeGreaterThan(pulseFrequency(0))
    expect(pulseFrequency(0)).toBeGreaterThan(0)
  })

  it('keeps radius above the surface for land and below for submarine', () => {
    expect(volcanoRadius(2, 3000)).toBeGreaterThan(2)
    expect(volcanoRadius(2, -2000)).toBeLessThan(2)
    expect(coneScale(3000)).toBeGreaterThan(0)
    expect(coneScale(-2000)).toBeGreaterThan(0)
  })
})
