import { describe, expect, it } from 'vitest'
import { GLOBE_R } from './geo'
import { buildRiverGeometry, riverColor, riverStrength, type RiversData } from './rivers'

const data: RiversData = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    properties: { scalerank: 1, strokeweig: 0.6, featurecla: 'River', name: 'Test' },
    geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1], [2, 1]] },
  }],
}

describe('glowing river network', () => {
  it('uses brighter colours for higher-ranked rivers', () => {
    expect(riverColor(1)[2]).toBeGreaterThan(riverColor(6)[2])
    expect(riverColor(20)).toEqual(riverColor(6))
    expect(riverStrength(1, 0.6)).toBeGreaterThan(riverStrength(6, 0.1))
    expect(riverStrength(1, 1)).toBeLessThanOrEqual(1)
  })

  it('builds one segment per centreline pair above the globe surface', () => {
    const g = buildRiverGeometry(data)
    expect(g.positions.length).toBe(12) // 2 segments x 2 vertices x xyz
    expect(g.colors.length).toBe(12)
    expect(g.strengths.length).toBe(4)
    for (let i = 0; i < g.positions.length; i += 3) {
      const r = Math.hypot(g.positions[i], g.positions[i + 1], g.positions[i + 2])
      expect(r).toBeCloseTo(GLOBE_R * 1.002, 4)
    }
  })

  it('handles MultiLineString geometry', () => {
    const multi: RiversData = {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        properties: { scalerank: 3, strokeweig: 0.3, featurecla: 'River', name: null },
        geometry: { type: 'MultiLineString', coordinates: [
          [[0, 0], [1, 0]], [[10, 10], [11, 11], [12, 12]],
        ] },
      }],
    }
    expect(buildRiverGeometry(multi).strengths.length).toBe(6)
  })
})
