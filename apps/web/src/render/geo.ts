/** Geometry, projection and sampling helpers shared by all render layers. */
import * as THREE from 'three'
import type { GridInfo } from './types'

export const GLOBE_R = 2
export const R_ATMOSPHERE = 2.16
export const EARTH_KM = 6371

/** Live aircraft sit just above the surface; altitude is visually exaggerated
 *  so cruise levels remain distinguishable at globe scale. */
export function flightRadius(altM: number): number {
  const altitude = Math.min(20000, Math.max(0, Number(altM) || 0))
  return GLOBE_R * (1.004 + 3 * altitude / (EARTH_KM * 1000))
}

/** lon/lat (degrees, east/north positive) -> ECEF on a sphere of radius r.
 *  Convention: lon=0 faces +Z, lon=90E faces +X, north pole is +Y. */
export function ll2xyz(lon: number, lat: number, r = GLOBE_R): THREE.Vector3 {
  const la = THREE.MathUtils.degToRad(lat)
  const lo = THREE.MathUtils.degToRad(lon)
  return new THREE.Vector3(
    r * Math.cos(la) * Math.sin(lo),
    r * Math.sin(la),
    r * Math.cos(la) * Math.cos(lo),
  )
}

export function xyz2ll(p: THREE.Vector3): [number, number] {
  const n = p.clone().normalize()
  const lat = THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(n.y, -1, 1)))
  const lon = THREE.MathUtils.radToDeg(Math.atan2(n.x, n.z))
  return [lon, lat]
}

/** Regular lat/lon sphere with UVs matching the -180..180 / -90..90 grid. */
export function sphereGeometry(radius: number, segments = 128, rings = 64): THREE.BufferGeometry {
  const pos: number[] = []
  const uv: number[] = []
  const idx: number[] = []
  for (let j = 0; j <= rings; j++) {
    const lat = -90 + (j / rings) * 180
    for (let i = 0; i <= segments; i++) {
      const lon = -180 + (i / segments) * 360
      const v = ll2xyz(lon, lat, radius)
      pos.push(v.x, v.y, v.z)
      // DataTexture row 0 is the south pole; THREE samples v=0 at row 0.
      uv.push(i / segments, j / rings)
    }
  }
  for (let j = 0; j < rings; j++) {
    for (let i = 0; i < segments; i++) {
      const a = j * (segments + 1) + i
      const b = a + segments + 1
      // Counter-clockwise when viewed from outside -> outward normals.
      idx.push(a, a + 1, b, b, a + 1, b + 1)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  g.setIndex(idx)
  g.computeVertexNormals()
  return g
}

/** Patch geometry over a bbox; optional per-vertex elevation displacement.
 *  Elevation is in metres; elevationScale converts to globe radius units. */
export function patchGeometry(
  bbox: [number, number, number, number],
  radius: number,
  nxSeg = 96,
  nySeg = 64,
  elevation?: Float32Array,
  elevGrid?: GridInfo,
  elevScale = 2e-6,
): THREE.BufferGeometry {
  const [w, s, e, n] = bbox
  const pos: number[] = []
  const uv: number[] = []
  const idx: number[] = []
  for (let j = 0; j <= nySeg; j++) {
    const lat = s + (j / nySeg) * (n - s)
    for (let i = 0; i <= nxSeg; i++) {
      const lon = w + (i / nxSeg) * (e - w)
      let h = 0
      if (elevation && elevGrid) {
        const fi = THREE.MathUtils.clamp((lon - elevGrid.lon0) / elevGrid.dx, 0, elevGrid.nx - 1)
        const fj = THREE.MathUtils.clamp((lat - elevGrid.lat0) / elevGrid.dy, 0, elevGrid.ny - 1)
        const i0 = Math.floor(fi); const j0 = Math.floor(fj)
        const i1 = Math.min(i0 + 1, elevGrid.nx - 1); const j1 = Math.min(j0 + 1, elevGrid.ny - 1)
        const tx = fi - i0; const ty = fj - j0
        const v00 = elevation[j0 * elevGrid.nx + i0]; const v10 = elevation[j0 * elevGrid.nx + i1]
        const v01 = elevation[j1 * elevGrid.nx + i0]; const v11 = elevation[j1 * elevGrid.nx + i1]
        const val = (v00 * (1 - tx) + v10 * tx) * (1 - ty) + (v01 * (1 - tx) + v11 * tx) * ty
        if (Number.isFinite(val)) h = val * elevScale
      }
      const v = ll2xyz(lon, lat, radius + h)
      pos.push(v.x, v.y, v.z)
      uv.push(i / nxSeg, j / nySeg)
    }
  }
  for (let j = 0; j < nySeg; j++) {
    for (let i = 0; i < nxSeg; i++) {
      const a = j * (nxSeg + 1) + i
      const b = a + nxSeg + 1
      idx.push(a, a + 1, b, b, a + 1, b + 1)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  g.setIndex(idx)
  g.computeVertexNormals()
  return g
}

/** Bilinear sample of ncomp values at (lon,lat), returning NaN for holes. */
export function sampleGrid(values: Float32Array, grid: GridInfo, ncomp: number, lon: number, lat: number): number[] {
  const { nx, ny, lon0, lat0, dx, dy, wrap_longitude } = grid
  let fi = (lon - lon0) / dx
  const fj = (lat - lat0) / dy
  if (wrap_longitude) fi = ((fi % nx) + nx) % nx
  else if (fi < 0 || fi > nx - 1) return new Array(ncomp).fill(NaN)
  const fjClamped = THREE.MathUtils.clamp(fj, 0, ny - 1)
  const i0 = Math.floor(fi)
  const i1 = wrap_longitude ? (i0 + 1) % nx : Math.min(i0 + 1, nx - 1)
  const j0 = Math.floor(fjClamped)
  const j1 = Math.min(j0 + 1, ny - 1)
  const tx = fi - Math.floor(fi)
  const ty = fjClamped - j0
  const out: number[] = []
  for (let k = 0; k < ncomp; k++) {
    let num = 0; let den = 0
    const corners: Array<[number, number, number]> = [
      [j0, i0, (1 - tx) * (1 - ty)], [j0, i1, tx * (1 - ty)],
      [j1, i0, (1 - tx) * ty], [j1, i1, tx * ty],
    ]
    for (const [j, i, w] of corners) {
      const v = values[(j * nx + i) * ncomp + k]
      if (!Number.isFinite(v)) continue
      num += w * v; den += w
    }
    out.push(den > 0 ? num / den : NaN)
  }
  return out
}

/** Equirectangular basemap texture from Natural Earth GeoJSON. */
export function buildBasemapTexture(geojson: any, width = 4096, height = 2048): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const ctx = canvas.getContext('2d')!
  // Deep ocean gradient with latitude shading.
  const ocean = ctx.createLinearGradient(0, 0, 0, height)
  ocean.addColorStop(0, '#071726'); ocean.addColorStop(0.25, '#0b2237')
  ocean.addColorStop(0.5, '#0e2b45'); ocean.addColorStop(0.75, '#0b2237'); ocean.addColorStop(1, '#071726')
  ctx.fillStyle = ocean; ctx.fillRect(0, 0, width, height)
  // Subtle bathymetry-like bands.
  ctx.strokeStyle = 'rgba(90,150,195,0.05)'; ctx.lineWidth = 1
  for (let lat = -80; lat <= 80; lat += 10) {
    const y = ((90 - lat) / 180) * height
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
  }
  const project = (lon: number, lat: number): [number, number] =>
    [((lon + 180) / 360) * width, ((90 - lat) / 180) * height]

  const features = geojson?.features || []
  // Draw each polygon: fill and coastline stroke. Split at antimeridian.
  ctx.fillStyle = '#2c4d43'
  ctx.strokeStyle = 'rgba(150,210,190,0.65)'
  ctx.lineWidth = 1.4
  for (const f of features) {
    const g = f.geometry
    if (!g) continue
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : []
    for (const poly of polys) {
      for (const ring of poly) {
        ctx.beginPath()
        let started = false
        let prevX = -1
        for (const p of ring) {
          const [x, y] = project(p[0], p[1])
          // Break the path when crossing the antimeridian.
          if (prevX >= 0 && Math.abs(x - prevX) > width / 2) { ctx.stroke(); ctx.beginPath(); started = false }
          if (!started) { ctx.moveTo(x, y); started = true } else ctx.lineTo(x, y)
          prevX = x
        }
        if (started) { ctx.closePath(); ctx.fill(); ctx.stroke() }
      }
    }
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return tex
}
