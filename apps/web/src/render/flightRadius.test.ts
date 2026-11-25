import { describe, expect, it } from 'vitest'
import { GLOBE_R, flightRadius } from './geo'

describe('live flight airspace', () => {
  it('flies just above the surface and stays below the atmosphere', () => {
    expect(flightRadius(0)).toBeGreaterThan(GLOBE_R)
    expect(flightRadius(0)).toBeLessThan(GLOBE_R * 1.01)
    expect(flightRadius(12000)).toBeGreaterThan(flightRadius(0))
    expect(flightRadius(12000)).toBeLessThan(GLOBE_R * 1.05)
    expect(flightRadius(1e9)).toBeLessThan(GLOBE_R * 1.06)
  })

  it('never sinks below the surface for bad altitudes', () => {
    expect(flightRadius(-500)).toBe(flightRadius(0))
    expect(flightRadius(NaN)).toBe(flightRadius(0))
  })
})
