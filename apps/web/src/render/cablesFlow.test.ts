import { describe, expect, it } from 'vitest'
import { CableLayer } from './cables'

const cables = [{
  type: 'Feature',
  geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1], [2, 1]] },
}]

describe('flowing submarine cables', () => {
  it('carries progress and cable-id attributes alongside each segment vertex', () => {
    const layer = new CableLayer()
    layer.setData(cables, [])
    const geo = layer.lines.geometry
    const vertices = geo.getAttribute('position').count
    expect(vertices).toBeGreaterThan(0)
    expect(geo.getAttribute('aProgress').count).toBe(vertices)
    expect(geo.getAttribute('aCable').count).toBe(vertices)
    const pg = geo.getAttribute('aProgress')
    expect(pg.getX(0)).toBe(0)
    expect(pg.getX(pg.count - 1)).toBeCloseTo(1, 5)
    layer.dispose()
  })

  it('advances its shader clock', () => {
    const layer = new CableLayer()
    layer.setData(cables, [])
    const mat = layer.lines.material as any
    expect(mat.fragmentShader).toContain('vGlow')
    expect(mat.vertexShader).toContain('uTime * 0.13')
    layer.update(12)
    expect(mat.uniforms.uTime.value).toBe(12)
    layer.dispose()
  })
})
