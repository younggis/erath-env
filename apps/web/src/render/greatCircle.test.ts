import { describe, expect, it } from 'vitest'
import { arcHeight, sampleArc, slerp } from './greatCircle'

describe('great-circle arcs', () => {
  it('interpolates between airports without NaN', () => {
    const p = slerp({ lon: -74, lat: 40 }, { lon: 139, lat: 35 }, 0.5)
    expect(Number.isFinite(p.lon) && Number.isFinite(p.lat)).toBe(true)
    expect(p.lon).toBeGreaterThanOrEqual(-180)
    expect(p.lon).toBeLessThanOrEqual(180)
  })

  it('bows long routes higher and peaks at mid-arc', () => {
    expect(arcHeight(2.5)).toBeGreaterThan(arcHeight(0.2))
    const pts = sampleArc({ lon: -74, lat: 40 }, { lon: 139, lat: 35 }, 24)
    expect(pts.length).toBe(25)
    const mid = pts[Math.floor(pts.length / 2)]
    expect(mid.h).toBeGreaterThan(pts[0].h)
    expect(mid.h).toBeGreaterThan(pts[pts.length - 1].h)
    expect(pts.every(p => Number.isFinite(p.lon) && Number.isFinite(p.lat) && Number.isFinite(p.h))).toBe(true)
  })
})
