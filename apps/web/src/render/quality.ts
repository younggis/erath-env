/** Lightweight, dependency-free rendering quality policy (no WebGL/DOM here). */
export type QualityTier = 'high' | 'medium' | 'low'

export interface QualityProfile {
  /** Cap applied to devicePixelRatio. */
  pixelRatioCap: number
  /** Raymarch steps for the volumetric cloud layer. */
  cloudSteps: number
  /** Bloom strength; bloom is switched off entirely at the lowest tier. */
  bloomStrength: number
  bloomEnabled: boolean
}

/** Ordered from best to worst so downgrade/upgrade is just an index shift. */
export const QUALITY_TIERS: QualityTier[] = ['high', 'medium', 'low']

export const QUALITY_PROFILES: Record<QualityTier, QualityProfile> = {
  high: { pixelRatioCap: 2, cloudSteps: 64, bloomStrength: 0.55, bloomEnabled: true },
  medium: { pixelRatioCap: 1.5, cloudSteps: 40, bloomStrength: 0.42, bloomEnabled: true },
  low: { pixelRatioCap: 1, cloudSteps: 24, bloomStrength: 0.35, bloomEnabled: false },
}

/** 3-second EMA. FPS samples arrive about once per second. */
export const FPS_EMA_ALPHA = 1 - Math.exp(-1 / 3) // ~0.2835
export const FPS_DOWN = 26
export const FPS_UP = 45
/** Consecutive EMA samples needed before a tier actually changes. */
export const TIER_STREAK = 3

export function updateFpsEma(prev: number, sample: number, alpha = FPS_EMA_ALPHA): number {
  return prev + (sample - prev) * alpha
}

export interface TierState {
  tier: QualityTier
  lowStreak: number
  highStreak: number
}

/** Hysteresis: a streak of low FPS steps down, a streak of high FPS steps up.
 *  The 26..45 band is neutral and clears both streaks. */
export function nextQualityTier(emaFps: number, state: TierState): TierState {
  let { tier, lowStreak, highStreak } = state
  if (emaFps < FPS_DOWN) { lowStreak++; highStreak = 0 }
  else if (emaFps > FPS_UP) { highStreak++; lowStreak = 0 }
  else { lowStreak = 0; highStreak = 0 }

  const i = QUALITY_TIERS.indexOf(tier)
  if (lowStreak >= TIER_STREAK) {
    if (i < QUALITY_TIERS.length - 1) tier = QUALITY_TIERS[i + 1]
    lowStreak = 0
  } else if (highStreak >= TIER_STREAK) {
    if (i > 0) tier = QUALITY_TIERS[i - 1]
    highStreak = 0
  }
  return { tier, lowStreak, highStreak }
}

/** Holds the EMA and streak counters; the pure functions above do the deciding. */
export class QualityController {
  tier: QualityTier
  auto = true
  private ema = 0
  private hasSample = false
  private lowStreak = 0
  private highStreak = 0

  constructor(tier: QualityTier = 'high') { this.tier = tier }

  /** Feed the renderer's FPS measurement (roughly once per second). */
  sample(fps: number): QualityTier {
    if (!Number.isFinite(fps) || fps <= 0) return this.tier
    this.ema = this.hasSample ? updateFpsEma(this.ema, fps) : fps
    this.hasSample = true
    if (!this.auto) return this.tier
    const next = nextQualityTier(this.ema, {
      tier: this.tier, lowStreak: this.lowStreak, highStreak: this.highStreak,
    })
    this.tier = next.tier
    this.lowStreak = next.lowStreak
    this.highStreak = next.highStreak
    return this.tier
  }

  /** Manual selection locks the tier and stops automatic adjustments. */
  setTier(tier: QualityTier): void {
    this.auto = false
    this.tier = tier
    this.lowStreak = 0
    this.highStreak = 0
  }
}
