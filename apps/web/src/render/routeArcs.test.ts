import { describe, expect, it } from 'vitest'
import { RouteArcLayer } from './routeArcs'
import { sampleArc } from './greatCircle'

describe('flight route arcs', () => {
  it('keeps hairline brightness below the old heavy glow', () => {
    const layer = new RouteArcLayer()
    const frag = (layer.lines.material as any).fragmentShader as string
    expect(frag).toContain('0.045 + 0.28 * vGlow')
    expect(frag).toContain('0.18 + 0.55 * vGlow')
    expect(frag).not.toContain('0.14 + 0.80 * vGlow')
    layer.dispose()
  })

  it('still builds segment geometry from great-circle samples', () => {
    const pts = sampleArc({ lon: -74, lat: 40 }, { lon: -5, lat: 36 }, 18)
    expect(pts.length).toBe(19)
    expect(pts[0].progress).toBe(0)
    expect(pts[18].progress).toBeCloseTo(1, 5)
  })
})
