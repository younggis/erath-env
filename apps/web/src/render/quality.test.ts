import { describe, it, expect } from 'vitest'
import {
  QUALITY_PROFILES, updateFpsEma, nextQualityTier, QualityController,
  type TierState,
} from './quality'

describe('rendering quality policy (pure)', () => {
  it('keeps profiles monotonic and disables bloom only at low', () => {
    expect(QUALITY_PROFILES.high.pixelRatioCap).toBeGreaterThan(QUALITY_PROFILES.medium.pixelRatioCap)
    expect(QUALITY_PROFILES.medium.pixelRatioCap).toBeGreaterThan(QUALITY_PROFILES.low.pixelRatioCap)
    expect(QUALITY_PROFILES.high.cloudSteps).toBeGreaterThan(QUALITY_PROFILES.medium.cloudSteps)
    expect(QUALITY_PROFILES.medium.cloudSteps).toBeGreaterThan(QUALITY_PROFILES.low.cloudSteps)
    expect(QUALITY_PROFILES.high.bloomEnabled).toBe(true)
    expect(QUALITY_PROFILES.medium.bloomEnabled).toBe(true)
    expect(QUALITY_PROFILES.low.bloomEnabled).toBe(false)
  })

  it('smooths FPS with the 3-second EMA', () => {
    expect(updateFpsEma(60, 20)).toBeGreaterThan(20)
    expect(updateFpsEma(60, 20)).toBeLessThan(60)
    let ema = 60
    for (let i = 0; i < 40; i++) ema = updateFpsEma(ema, 20)
    expect(ema).toBeCloseTo(20, 1)
  })

  it('downgrades only after a streak of low FPS', () => {
    let s: TierState = { tier: 'high', lowStreak: 0, highStreak: 0 }
    s = nextQualityTier(20, s)
    expect(s.tier).toBe('high')
    s = nextQualityTier(20, s)
    expect(s.tier).toBe('high')
    s = nextQualityTier(20, s)
    expect(s.tier).toBe('medium')
  })

  it('upgrades only after a streak of high FPS', () => {
    let s: TierState = { tier: 'low', lowStreak: 0, highStreak: 0 }
    for (let i = 0; i < 2; i++) s = nextQualityTier(55, s)
    expect(s.tier).toBe('low')
    s = nextQualityTier(55, s)
    expect(s.tier).toBe('medium')
  })

  it('clears streaks in the neutral 26..45 band', () => {
    const s = nextQualityTier(35, { tier: 'high', lowStreak: 2, highStreak: 0 })
    expect(s.tier).toBe('high')
    expect(s.lowStreak).toBe(0)
  })

  it('locks the tier when set manually', () => {
    const c = new QualityController('high')
    c.setTier('low')
    expect(c.auto).toBe(false)
    for (let i = 0; i < 10; i++) c.sample(60)
    expect(c.tier).toBe('low')
  })

  it('drops to low after sustained low FPS', () => {
    const c = new QualityController('high')
    for (let i = 0; i < 20; i++) c.sample(20)
    expect(c.tier).toBe('low')
  })
})
