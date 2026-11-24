/** Geometry helpers: lon/lat <-> ECEF, grid sampling, basemap texture. */
import * as THREE from 'three'
import { palette, RANGES } from './palettes'

export const GLOBE_R = 2

/** East longitude, north latitude. lon=0 faces the camera at +Z. */
export function lonLatToVec3(lon: number, lat: number, r = GLOBE_R): THREE.Vector3 {
  const la = (lat * Math.PI) / 180
  const lo = (lon * Math.PI) / 180
  return new THREE.Vector3(
    r * Math.cos(la) * Math.sin(lo),
    r * Math.sin(la),
    r * Math.cos(la) * Math.cos(lo),
  )
}

export function vec3ToLonLat(v: THREE.Vector3): [number, number] {
  const n = v.clone().normalize()
  const lat = (Math.asin(Math.max(-1, Math.min(1, n.y))) * 180) / Math.PI
  const lon = (Math.atan2(n.x, n.z) * 180) / Math.PI
  return [lon, lat]
}

export interface GridInfo {
  nx: number; ny: number; lon0: number; lat0: number; dx: number; dy: number; wrap_longitude: boolean
}

/** Bilinear sample of a float32 grid stored as (ny,nx,ncomp). */
export function sampleGrid(values: Float32Array, grid: GridInfo, ncomp: number, lon: number, lat: number): number[] | null {
  const { nx, ny, lon0, lat0, dx, dy, wrap_longitude } = grid
  let fi = (lon - lon0) / dx
  const fjRaw = (lat - lat0) / dy
  if (wrap_longitude) fi = ((fi % nx) + nx) % nx
  else if (fi < 0 || fi > nx - 1) return null
  const fj = Math.max(0, Math.min(ny - 1, fjRaw))
  const i0 = Math.floor(fi); const i1 = wrap_longitude ? (i0 + 1) % nx : Math.min(i0 + 1, nx - 1)
  const j0 = Math.floor(fj); const j1 = Math.min(j0 + 1, ny - 1)
  const tx = fi - i0; const ty = fj - j0
  const out: number[] = []
  for (let k = 0; k < ncomp; k++) {
    let num = 0; let den = 0
    for (const [j, i, w] of [[j0, i0, (1 - tx) * (1 - ty)], [j0, i1, tx * (1 - ty)],
                            [j1, i0, (1 - tx) * ty], [j1, i1, tx * ty]] as number[][]) {
      const v = values[(j * nx + i) * ncomp + k]
      if (!Number.isFinite(v)) continue
      num += w * v; den += w
    }
    out.push(den > 0 ? num / den : NaN)
  }
  return out
}

/** Draw Natural Earth land polygons onto an equirectangular canvas texture. */
export function buildBasemap(geojson: any, width = 2048, height = 1024): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const ctx = canvas.getContext('2d')!
  const ocean = ctx.createLinearGradient(0, 0, 0, height)
  ocean.addColorStop(0, '#081627'); ocean.addColorStop(0.5, '#0d2740'); ocean.addColorStop(1, '#081627')
  ctx.fillStyle = ocean; ctx.fillRect(0, 0, width, height)
  // subtle latitude bands
  ctx.strokeStyle = 'rgba(120,180,220,0.06)'; ctx.lineWidth = 1
  for (let lat = -90; lat <= 90; lat += 15) {
    const y = ((90 - lat) / 180) * height
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
  }
  const project = (lon: number, lat: number): [number, number] => [((lon + 180) / 360) * width, ((90 - lat) / 180) * height]
  ctx.fillStyle = '#22463f'; ctx.strokeStyle = 'rgba(140,210,190,0.55)'; ctx.lineWidth = 0.8
  const features = geojson?.features || []
  for (const f of features) {
    const g = f.geometry
    if (!g) continue
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : []
    for (const poly of polys) {
      for (const ring of poly) {
        ctx.beginPath()
        ring.forEach((p: number[], i: number) => {
          const [x, y] = project(p[0], p[1])
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
        })
        ctx.closePath(); ctx.fill(); ctx.stroke()
      }
    }
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

/** Build a scalar/vector overlay texture from a grid binary. */
export function buildFieldTexture(buffer: ArrayBuffer, grid: GridInfo, ncomp: number,
                                  paletteName: string, range: [number, number], vectorSpeed = false): THREE.DataTexture {
  const values = new Float32Array(buffer)
  const { nx, ny } = grid
  const data = new Uint8Array(nx * ny * 4)
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const idx = ((j * nx) + i) * ncomp
      let v: number
      if (vectorSpeed && ncomp >= 2) {
        const u = values[idx]; const vv = values[idx + 1]
        v = Number.isFinite(u) && Number.isFinite(vv) ? Math.hypot(u, vv) : NaN
      } else {
        v = values[idx]
      }
      const o = ((j * nx) + i) * 4
      if (!Number.isFinite(v)) { data[o] = 0; data[o + 1] = 0; data[o + 2] = 0; data[o + 3] = 0; continue }
      const t = (v - range[0]) / (range[1] - range[0])
      const c = palette(paletteName, t) as number[]
      data[o] = c[0]; data[o + 1] = c[1]; data[o + 2] = c[2]
      data[o + 3] = c.length === 4 ? c[3] : 225
    }
  }
  const tex = new THREE.DataTexture(data, nx, ny, THREE.RGBAFormat)
  tex.needsUpdate = true
  tex.magFilter = THREE.LinearFilter
  tex.minFilter = THREE.LinearFilter
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

export function rangeFor(layerId: string): [number, number] {
  return RANGES[layerId] || [0, 1]
}

// RANGES are stored in source units (matching the binary data / colour mapping),
// but the legend is labelled with the layer's display_unit. Convert the legend
// numbers so e.g. snow depth 0–0.5 m reads 0–50 cm. Temperature RANGES are
// already in °C (display unit) so they are left unchanged.
const M_TO_MM = new Set(['ifs_tp'])
const M_TO_CM = new Set(['snow_depth', 'snow', 'ifs_sd'])
const PA_TO_HPA = new Set(['mslp', 'surface_pressure', 'ifs_msl'])
const M_TO_KM = new Set(['visibility_sfc'])
const GPM = new Set(['gh500'])
const J_TO_MJ = new Set(['ifs_ssrd'])

export function displayRangeFor(layerId: string): [number, number] {
  const [a, b] = rangeFor(layerId)
  let f = 1
  if (M_TO_MM.has(layerId)) f = 1000
  else if (M_TO_CM.has(layerId)) f = 100
  else if (PA_TO_HPA.has(layerId)) f = 0.01
  else if (M_TO_KM.has(layerId)) f = 0.001
  else if (GPM.has(layerId)) f = 1 / 9.80665
  else if (J_TO_MJ.has(layerId)) f = 1e-6
  return f === 1 ? [a, b] : [a * f, b * f]
}
