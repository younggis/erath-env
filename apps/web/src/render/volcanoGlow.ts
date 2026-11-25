/** Pure helpers for volcano 3D placement and lava-pulse activity. */
export interface Volcano {
  id: string
  name: string
  country: string
  region: string
  lat: number
  lon: number
  elev: number
  type: string
  status: string
  last_code: string
  last_year: number | null
}

const OLDEST = -7000
const NEWEST = 2026

/** 0 (dormant/ancient) .. 1 (erupted recently). Unknown -> 0.15. */
export function eruptionRecency(lastYear: number | null, nowYear = NEWEST): number {
  if (lastYear === null || !Number.isFinite(lastYear)) return 0.15
  const clamped = Math.min(nowYear, Math.max(OLDEST, lastYear))
  return (clamped - OLDEST) / (NEWEST - OLDEST)
}

/** Lava pulse frequency in Hz: recent eruptions pulse faster. */
export function pulseFrequency(recency: number): number {
  return 0.35 + 3.2 * Math.min(1, Math.max(0, recency))
}

/** Globe radius for a volcano: elevation in metres above/below sea level. */
export function volcanoRadius(globeRadius: number, elevMetres: number): number {
  return globeRadius * (1 + elevMetres / 6_371_000)
}

/** Instance cone scale (surface volcanoes are exaggerated for legibility). */
export function coneScale(elevMetres: number): number {
  const positive = Math.max(0, elevMetres)
  return 0.018 + Math.min(0.03, positive / 250000)
}
