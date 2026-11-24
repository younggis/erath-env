/** Great-circle interpolation helpers for smooth submarine-cable curves. */
export interface LonLat {
  lon: number
  lat: number
}

function toVec(lon: number, lat: number): [number, number, number] {
  const lo = lon * Math.PI / 180, la = lat * Math.PI / 180
  return [Math.cos(la) * Math.sin(lo), Math.sin(la), Math.cos(la) * Math.cos(lo)]
}

function toLonLat(v: [number, number, number]): LonLat {
  const len = Math.hypot(v[0], v[1], v[2]) || 1
  const x = v[0] / len, y = v[1] / len, z = v[2] / len
  return {
    lon: Math.atan2(x, z) * 180 / Math.PI,
    lat: Math.asin(Math.max(-1, Math.min(1, y))) * 180 / Math.PI,
  }
}

/** Spherical linear interpolation between two lon/lat points. */
export function slerpLonLat(a: LonLat, b: LonLat, t: number): LonLat {
  const va = toVec(a.lon, a.lat), vb = toVec(b.lon, b.lat)
  const dot = Math.max(-1, Math.min(1, va[0]*vb[0] + va[1]*vb[1] + va[2]*vb[2]))
  const omega = Math.acos(dot)
  if (omega < 1e-6) return { lon: a.lon, lat: a.lat }
  const s = Math.sin(omega)
  const w1 = Math.sin((1 - t) * omega) / s
  const w2 = Math.sin(t * omega) / s
  return toLonLat([
    va[0]*w1 + vb[0]*w2, va[1]*w1 + vb[1]*w2, va[2]*w1 + vb[2]*w2,
  ])
}

/** Resample a GeoJSON LineString to evenly spaced great-circle points. */
export function resampleLine(coords: number[][], maxStepDeg = 1.5): LonLat[] {
  if (!coords.length) return []
  const out: LonLat[] = [{ lon: coords[0][0], lat: coords[0][1] }]
  for (let i = 1; i < coords.length; i++) {
    const a = { lon: coords[i - 1][0], lat: coords[i - 1][1] }
    const b = { lon: coords[i][0], lat: coords[i][1] }
    const d = Math.acos(Math.max(-1, Math.min(1,
      Math.sin(a.lat*Math.PI/180)*Math.sin(b.lat*Math.PI/180) +
      Math.cos(a.lat*Math.PI/180)*Math.cos(b.lat*Math.PI/180)*Math.cos((b.lon-a.lon)*Math.PI/180)))) * 180 / Math.PI
    const steps = Math.max(1, Math.ceil(d / Math.max(0.1, maxStepDeg)))
    for (let s = 1; s <= steps; s++) out.push(slerpLonLat(a, b, s / steps))
  }
  return out
}

/** Uniformity metric: max / min consecutive angular step (1.0 = perfectly even). */
export function smoothness(points: LonLat[]): number {
  if (points.length < 3) return 1
  const steps: number[] = []
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i]
    const d = Math.hypot(b.lon - a.lon, b.lat - a.lat)
    if (d > 1e-9) steps.push(d)
  }
  if (steps.length < 2) return 1
  return Math.max(...steps) / Math.min(...steps)
}
