/** Pure SGP4 helpers: TLE -> geodetic EPSG:4326 + altitude (km). */
import {
  twoline2satrec, propagate, gstime, eciToGeodetic,
  degreesLat, degreesLong,
} from 'satellite.js'

export interface SatPosition {
  lon: number
  lat: number
  altKm: number
}

export interface TleRecord {
  name: string
  norad_id: string
  line1: string
  line2: string
  group: string
}

export function satrecFromTle(line1: string, line2: string) {
  return twoline2satrec(line1, line2)
}

/** Propagate one TLE to `date` and convert ECI -> ECF -> geodetic. */
export function propagateGeodetic(line1: string, line2: string, date: Date): SatPosition | null {
  try {
    const satrec = satrecFromTle(line1, line2)
    const pv: any = propagate(satrec, date)
    const pos = pv && pv.position
    if (!pos || typeof pos === 'boolean') return null
    const gmst = gstime(date)
    const geo: any = eciToGeodetic(pos, gmst)
    const lon = degreesLong(geo.longitude)
    const lat = degreesLat(geo.latitude)
    const altKm = geo.height
    if (![lon, lat, altKm].every(v => typeof v === 'number' && Number.isFinite(v))) return null
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return null
    return { lon, lat, altKm }
  } catch {
    return null
  }
}

/** Earth-central angle of the visibility footprint for a nadir sensor. */
export function footprintAngle(altKm: number, earthKm = 6371): number {
  if (!Number.isFinite(altKm) || altKm <= 0) return 0
  return Math.acos(Math.min(1, earthKm / (earthKm + altKm)))
}

/** Sample one orbital revolution as lon/lat points (approximate ring). */
export function orbitRing(line1: string, line2: string, date: Date,
                          samples = 72, stepSeconds = 120): SatPosition[] {
  const out: SatPosition[] = []
  for (let i = 0; i < samples; i++) {
    const p = propagateGeodetic(line1, line2,
      new Date(date.getTime() + i * stepSeconds * 1000))
    if (p) out.push(p)
  }
  return out
}
