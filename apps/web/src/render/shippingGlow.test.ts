import { describe, expect, it } from 'vitest'
import { EARTH_FRAG, makeEarthMaterial } from './shaders'

describe('shipping-density night glow', () => {
  it('registers a data texture and a controllable strength uniform', () => {
    const material = makeEarthMaterial(null, null)
    expect(material.uniforms.uShippingMap).toBeDefined()
    expect(material.uniforms.uShippingStrength.value).toBe(0)
    material.uniforms.uShippingStrength.value = 1
    expect(material.uniforms.uShippingStrength.value).toBe(1)
    material.dispose()
  })

  it('glows only over the ocean, most strongly at night and the terminator', () => {
    const where = EARTH_FRAG.indexOf('vec3 col = mix(night, day, dayAmt);')
    expect(EARTH_FRAG).toContain('uniform sampler2D uShippingMap')
    expect(EARTH_FRAG.indexOf('uShippingStrength', where)).toBeGreaterThan(where)
    expect(EARTH_FRAG).toContain('ocean * lane * uShippingStrength')
    expect(EARTH_FRAG).toContain('0.12 + 0.88 * (1.0 - dayAmt)')
    expect(EARTH_FRAG).toContain('term*1.2 + rim*0.6')
    // Sun glint / foam are suppressed first, so ocean highlights survive.
    expect(EARTH_FRAG).toContain('1.0 - clamp(spec + foam, 0.0, 1.0)')
  })

  it('keeps the glow inside the base surface pass, below clouds and particles', () => {
    const glowEnd = EARTH_FRAG.indexOf('col += gold * glow')
    const cloud = EARTH_FRAG.indexOf('Animated thin cirrus veil')
    const rim = EARTH_FRAG.indexOf('Fresnel atmospheric rim')
    expect(glowEnd).toBeGreaterThan(-1)
    expect(glowEnd).toBeLessThan(cloud)
    expect(cloud).toBeLessThan(rim)
  })
})
