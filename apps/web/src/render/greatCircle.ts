/** Pure great-circle interpolation for flight-route arcs. */
export interface GeoPoint {
  lon: number
  lat: number
}

function toVec(p: GeoPoint): [number, number, number] {
  const lo = p.lon * Math.PI / 180, la = p.lat * Math.PI / 180
  return [Math.cos(la) * Math.sin(lo), Math.sin(la), Math.cos(la) * Math.cos(lo)]
}

function toLonLat(v: [number, number, number]): GeoPoint {
  const len = Math.hypot(v[0], v[1], v[2]) || 1
  return {
    lon: Math.atan2(v[0] / len, v[2] / len) * 180 / Math.PI,
    lat: Math.asin(Math.max(-1, Math.min(1, v[1] / len))) * 180 / Math.PI,
  }
}

/** Spherical linear interpolation between two airports. */
export function slerp(a: GeoPoint, b: GeoPoint, t: number): GeoPoint {
  const va = toVec(a), vb = toVec(b)
  const dot = Math.max(-1, Math.min(1, va[0]*vb[0] + va[1]*vb[1] + va[2]*vb[2]))
  const omega = Math.acos(dot)
  if (omega < 1e-6) return { lon: a.lon, lat: a.lat }
  const s = Math.sin(omega)
  const w1 = Math.sin((1 - t) * omega) / s, w2 = Math.sin(t * omega) / s
  return toLonLat([va[0]*w1+vb[0]*w2, va[1]*w1+vb[1]*w2, va[2]*w1+vb[2]*w2])
}

/** Central angle in radians between two airports. */
export function arcAngle(a: GeoPoint, b: GeoPoint): number {
  const va = toVec(a), vb = toVec(b)
  return Math.acos(Math.max(-1, Math.min(1, va[0]*vb[0]+va[1]*vb[1]+va[2]*vb[2])))
}

/** Arc apex height factor: long routes bow higher above the globe. */
export function arcHeight(angle: number): number {
  return 0.02 + Math.min(0.32, angle / Math.PI * 0.42)
}

/** Evenly spaced points (lon/lat/heightFactor) along a great-circle arc. */
export function sampleArc(a: GeoPoint, b: GeoPoint, segments = 48):
  { lon: number; lat: number; h: number; progress: number }[] {
  const angle = arcAngle(a, b)
  const h = arcHeight(angle)
  const out = []
  for (let i = 0; i <= segments; i++) {
    const t = i / segments
    const p = slerp(a, b, t)
    out.push({ lon: p.lon, lat: p.lat, h: h * Math.sin(Math.PI * t), progress: t })
  }
  return out
}
