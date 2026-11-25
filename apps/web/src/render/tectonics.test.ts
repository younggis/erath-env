import { describe, expect, it } from 'vitest'
import { boundaryRadius, classifyBoundary } from './tectonics'

describe('tectonic boundaries', () => {
  it('honours explicit subduction and infers ridges from plate pairs', () => {
    expect(classifyBoundary({ Type: 'subduction', PlateA: 'EU', PlateB: 'AF' })).toBe('subduction')
    expect(classifyBoundary({ PlateA: 'NA', PlateB: 'EU' })).toBe('ridge')
    expect(classifyBoundary({ PlateA: 'AF', PlateB: 'SA' })).toBe('ridge')
  })

  it('treats unknown pairs as transform', () => {
    expect(classifyBoundary({ PlateA: 'XX', PlateB: 'YY' })).toBe('transform')
  })

  it('lifts boundaries above the globe surface to avoid z-fighting', () => {
    expect(boundaryRadius(2.0)).toBeGreaterThan(2.0)
    const r = boundaryRadius(2.0)
    expect(r - 2.0).toBeGreaterThan(0.01)
    expect(r - 2.0).toBeLessThan(0.05)
  })
})
