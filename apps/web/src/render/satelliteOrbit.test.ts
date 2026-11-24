import { describe, expect, it } from 'vitest'
import { footprintAngle, orbitRing, propagateGeodetic, type TleRecord } from './satelliteOrbit'

const ISS = {
  name: 'ISS (ZARYA)', norad_id: '25544', group: 'stations',
  line1: '1 25544U 98067A   26327.91294507  .00005691  00000+0  10921-3 0  9993',
  line2: '2 25544  51.6322 229.6520 0007379  58.6021 301.5689 15.49568558596519',
} as TleRecord

describe('SGP4 geodetic conversion', () => {
  it('returns finite EPSG:4326 coordinates and altitude', () => {
    const pos = propagateGeodetic(ISS.line1, ISS.line2, new Date('2026-11-25T00:00:00Z'))
    expect(pos).not.toBeNull()
    expect(Number.isFinite(pos!.lon)).toBe(true)
    expect(Number.isFinite(pos!.lat)).toBe(true)
    expect(Number.isFinite(pos!.altKm)).toBe(true)
    expect(pos!.lon).toBeGreaterThanOrEqual(-180)
    expect(pos!.lon).toBeLessThanOrEqual(180)
    expect(pos!.lat).toBeGreaterThanOrEqual(-90)
    expect(pos!.lat).toBeLessThanOrEqual(90)
    expect(pos!.altKm).toBeGreaterThan(100)  // LEO altitude
  })

  it('returns null for malformed TLE instead of NaN', () => {
    expect(propagateGeodetic('bad', 'bad', new Date())).toBeNull()
  })

  it('samples a finite orbit ring', () => {
    const ring = orbitRing(ISS.line1, ISS.line2, new Date('2026-11-25T00:00:00Z'), 12, 300)
    expect(ring.length).toBeGreaterThan(8)
    expect(ring.every(p => Number.isFinite(p.lon) && Number.isFinite(p.lat))).toBe(true)
  })

  it('computes a sensible FOV angle', () => {
    const a = footprintAngle(400)
    expect(a).toBeGreaterThan(0)
    expect(a).toBeLessThan(Math.PI / 2)
    expect(footprintAngle(0)).toBe(0)
  })
})
