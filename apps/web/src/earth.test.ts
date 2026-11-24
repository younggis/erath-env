import { describe, it, expect } from 'vitest'
import { sampleGrid, lonLatToVec3, vec3ToLonLat, type GridInfo } from './earth'

describe('earth grid & geometry', () => {
  const grid: GridInfo = { nx: 4, ny: 3, lon0: -180, lat0: -90, dx: 120, dy: 90, wrap_longitude: true }
  // (ny,nx,1) values = j*10+i
  const vals = new Float32Array(Array.from({ length: 12 }, (_, k) => k))

  it('samples bilinear values', () => {
    expect(sampleGrid(vals, grid, 1, -180, -90)![0]).toBeCloseTo(0)
    expect(sampleGrid(vals, grid, 1, -60, 0)![0]).toBeCloseTo(5)
  })

  it('wraps the antimeridian on a 0..360 grid', () => {
    const g360: GridInfo = { nx: 4, ny: 2, lon0: 0, lat0: 0, dx: 90, dy: 90, wrap_longitude: true }
    const v = new Float32Array(Array.from({ length: 8 }, (_, k) => k))
    expect(sampleGrid(v, g360, 1, 180, 0)![0]).toBeCloseTo(sampleGrid(v, g360, 1, -180, 0)![0])
    expect(sampleGrid(v, g360, 1, 180, 0)![0]).toBeCloseTo(2)
  })

  it('round-trips lon/lat through ECEF', () => {
    for (const [lon, lat] of [[0, 0], [139.7, 35.5], [-180, -80], [90, 45]]) {
      const [lo, la] = vec3ToLonLat(lonLatToVec3(lon, lat))
      expect(lo).toBeCloseTo(lon, 4); expect(la).toBeCloseTo(lat, 4)
    }
  })
})
