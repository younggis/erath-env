import { describe, it, expect } from 'vitest'
import {
  gpuWindTextureSize,
  gpuWindStateIndex,
  gpuWindStateUv,
  gpuWindGridUv,
  type WindGridUvInfo,
} from './gpuWind'

describe('gpu wind pure index / uv helpers', () => {
  const global: WindGridUvInfo = {
    nx: 4, ny: 2, lon0: -180, lat0: -90, dx: 90, dy: 90, wrap_longitude: true,
  }

  it('uses the smallest square-ish state texture that fits the count', () => {
    expect(gpuWindTextureSize(1)).toEqual({ side: 1, width: 1, height: 1 })
    expect(gpuWindTextureSize(10)).toEqual({ side: 4, width: 4, height: 3 })
    const s = gpuWindTextureSize(8192)
    expect(s.side).toBe(91)
    expect(s.width * s.height).toBeGreaterThanOrEqual(8192)
    expect(s.height).toBe(Math.ceil(8192 / s.side))
  })

  it('maps particle indices to texel coordinates row by row', () => {
    expect(gpuWindStateIndex(0, 4)).toEqual([0, 0])
    expect(gpuWindStateIndex(3, 4)).toEqual([3, 0])
    expect(gpuWindStateIndex(4, 4)).toEqual([0, 1])
    expect(gpuWindStateIndex(8191, 91)).toEqual([1, 90])
  })

  it('samples texel centres, never texel corners', () => {
    expect(gpuWindStateUv(0, 4, 4, 4)).toEqual([0.125, 0.125])
    expect(gpuWindStateUv(5, 4, 4, 4)).toEqual([0.375, 0.375])
    const [u, v] = gpuWindStateUv(8191, 91, 91, 91)
    expect(u).toBeCloseTo(1.5 / 91, 6)
    expect(v).toBeCloseTo(90.5 / 91, 6)
  })

  it('maps lon/lat to wind field uv with texel centres', () => {
    const [u0, v0] = gpuWindGridUv(-180, -90, global)
    expect(u0).toBeCloseTo(0.5 / 4, 6)
    expect(v0).toBeCloseTo(0.5 / 2, 6)
    const [u1, v1] = gpuWindGridUv(-135, 0, global)
    expect(u1).toBeCloseTo(0.25, 6)
    expect(v1).toBeCloseTo(0.75, 6)
  })

  it('wraps longitude and clamps latitude for global grids', () => {
    expect(gpuWindGridUv(180, -90, global)[0]).toBeCloseTo(gpuWindGridUv(-180, -90, global)[0], 6)
    expect(gpuWindGridUv(-225, 0, global)[0]).toBeCloseTo(gpuWindGridUv(135, 0, global)[0], 6)
    expect(gpuWindGridUv(-135, 120, global)[1]).toBeCloseTo(1.5 / 2, 6)
    expect(gpuWindGridUv(-135, -120, global)[1]).toBeCloseTo(0.5 / 2, 6)
  })

  it('clamps both axes for regional (non-wrapping) grids', () => {
    const regional: WindGridUvInfo = {
      nx: 4, ny: 3, lon0: 100, lat0: 0, dx: 1, dy: 1, wrap_longitude: false,
    }
    const outside = gpuWindGridUv(99, -5, regional)
    expect(outside[0]).toBeCloseTo(0.5 / 4, 6)
    expect(outside[1]).toBeCloseTo(0.5 / 3, 6)
    const inside = gpuWindGridUv(105, 1, regional)
    expect(inside[0]).toBeCloseTo(3.5 / 4, 6)
    expect(inside[1]).toBeCloseTo(1.5 / 3, 6)
  })
})
