import { describe, expect, it } from 'vitest'
import { resampleLine, slerpLonLat, smoothness, type LonLat } from './cableGeometry'

describe('submarine cable geometry', () => {
  it('slerps between two points without NaN', () => {
    const p = slerpLonLat({lon: 0, lat: 0}, {lon: 90, lat: 30}, 0.5)
    expect(Number.isFinite(p.lon) && Number.isFinite(p.lat)).toBe(true)
    expect(p.lon).toBeGreaterThan(0)
    expect(p.lat).toBeGreaterThan(0)
  })

  it('resamples long segments into evenly spaced points', () => {
    const line = [[-70, 40], [0, 10], [100, 5]]
    const pts = resampleLine(line, 2)
    expect(pts.length).toBeGreaterThan(60)
    expect(pts.every(p => Number.isFinite(p.lon) && Number.isFinite(p.lat))).toBe(true)
    expect(pts.every(p => p.lon >= -180 && p.lon <= 180 && p.lat >= -90 && p.lat <= 90)).toBe(true)
    // Even spacing: regularity metric close to 1 (no huge jumps).
    expect(smoothness(pts)).toBeLessThan(3)
  })

  it('keeps short lines untouched apart from endpoints', () => {
    const pts = resampleLine([[1, 1], [1.2, 1.2]], 2)
    expect(pts.length).toBe(2)
    expect(smoothness(pts)).toBe(1)
  })
})
