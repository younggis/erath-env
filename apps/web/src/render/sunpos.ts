/** Real solar position from UTC time (NOAA solar calculator algorithm).
 *  Returns the sub-solar point — the lat/lon where the sun is directly
 *  overhead — and the sun direction vector in the ECEF convention used by
 *  ll2xyz: lon=0 -> +Z, lon=90E -> +X, north pole -> +Y.
 */
import * as THREE from 'three'

const DEG = Math.PI / 180

function julianDay(date: Date): number {
  return date.getTime() / 86400000 + 2440587.5
}

/** NOAA low-precision solar formula: declination + equation of time. */
export function solarInfo(date: Date): { declination: number; eqTimeMin: number } {
  const n = julianDay(date) - 2451545.0 // days since J2000.0
  const L = (280.460 + 0.9856474 * n) % 360
  const g = ((357.528 + 0.9856003 * n) % 360) * DEG
  const lambda = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * DEG
  const eps = (23.439 - 0.0000004 * n) * DEG
  const declination = Math.asin(Math.sin(eps) * Math.sin(lambda)) / DEG
  const ra = Math.atan2(Math.cos(eps) * Math.sin(lambda), Math.cos(lambda)) / DEG
  let eqTimeMin = 4 * (L - ra)
  // Normalise equation of time to [-20, 20] minutes.
  while (eqTimeMin > 20) eqTimeMin -= 1440 / 60
  while (eqTimeMin < -20) eqTimeMin += 1440 / 60
  return { declination, eqTimeMin }
}

/** Sub-solar longitude: subsolar point has local solar time = 12:00.
 *  solarTime(min) = utcMinutes + eqTime + 4*lonEast
 *  -> lonEast = (720 - utcMinutes - eqTime) / 4
 */
export function subsolarLongitude(date: Date): number {
  const { eqTimeMin } = solarInfo(date)
  const utcMinutes = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60
  let lon = (720 - utcMinutes - eqTimeMin) / 4
  while (lon < -180) lon += 360
  while (lon > 180) lon -= 360
  return lon
}

/** Sub-solar latitude (solar declination). */
export function subsolarLatitude(date: Date): number {
  return solarInfo(date).declination
}

/** Sun direction vector in ECEF for the given UTC instant. */
export function sunDirection(date: Date): THREE.Vector3 {
  const lat = subsolarLatitude(date) * DEG
  const lon = subsolarLongitude(date) * DEG
  return new THREE.Vector3(
    Math.cos(lat) * Math.sin(lon),
    Math.sin(lat),
    Math.cos(lat) * Math.cos(lon),
  ).normalize()
}

/** Whether a point is in daylight given the sun direction. */
export function isDaylight(lon: number, lat: number, sun: THREE.Vector3): boolean {
  const la = lat * DEG, lo = lon * DEG
  const p = new THREE.Vector3(Math.cos(la) * Math.sin(lo), Math.sin(la), Math.cos(la) * Math.cos(lo))
  return p.dot(sun) > 0
}
