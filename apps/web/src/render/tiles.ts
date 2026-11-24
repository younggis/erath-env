/** Two-level high-resolution satellite tiles on the globe (Esri World Imagery).
 *
 * A coarse "context" patch covers the whole visible area at a lower zoom, and
 * a fine "detail" patch covers the centre at a higher zoom — a lightweight
 * LOD pyramid. This gives county/street detail in the centre while the rest of
 * the view stays sharp, without the huge tile counts of a full quadtree.
 *
 * Attribution: Esri, Maxar, Earthstar Geographics, and the GIS User Community.
 */
import * as THREE from 'three'
import { GLOBE_R } from './geo'

const TILE_URL = (z: number, y: number, x: number) =>
  `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`
const ATTRIB = 'Esri, Maxar, Earthstar Geographics'
const MAX_ZOOM = 14
const TILE_SIZE = 256

interface TileKey { z: number; x: number; y: number }
function keyOf(k: TileKey): string { return `${k.z}/${k.x}/${k.y}` }
function lon2tile(lon: number, z: number): number {
  return Math.floor(((lon + 180) / 360) * Math.pow(2, z))
}
function lat2tile(lat: number, z: number): number {
  const r = (lat * Math.PI) / 180
  return Math.floor(((1 - Math.asinh(Math.tan(r)) / Math.PI) / 2) * Math.pow(2, z))
}
function tile2lon(x: number, z: number): number { return (x / Math.pow(2, z)) * 360 - 180 }
function tile2lat(y: number, z: number): number {
  return (180 / Math.PI) * Math.atan(Math.sinh(Math.PI - (2 * Math.PI * y) / Math.pow(2, z)))
}
function resolution(z: number, lat: number): number {
  return 156543.03 * Math.cos(lat * Math.PI / 180) / Math.pow(2, z)
}

function patchGeometry(west: number, east: number, south: number, north: number,
                       radius: number, nx = 80, ny = 80): THREE.BufferGeometry {
  const pos: number[] = [], uv: number[] = [], idx: number[] = []
  for (let j = 0; j <= ny; j++) {
    const lat = south + (j / ny) * (north - south)
    for (let i = 0; i <= nx; i++) {
      const lon = west + (i / nx) * (east - west)
      const la = (lat * Math.PI) / 180, lo = (lon * Math.PI) / 180
      pos.push(radius * Math.cos(la) * Math.sin(lo), radius * Math.sin(la), radius * Math.cos(la) * Math.cos(lo))
      uv.push(i / nx, j / ny)
    }
  }
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    const a = j * (nx + 1) + i, b = a + nx + 1
    idx.push(a, a + 1, b, b, a + 1, b + 1)
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  g.setIndex(idx); g.computeVertexNormals()
  return g
}

export interface TileStatus {
  zoom: number; detailZoom: number; tiles: number; resolutionM: number
  state: 'idle' | 'loading' | 'ready' | 'error'; attribution: string
}

interface Composite { mesh: THREE.Mesh; material: THREE.MeshBasicMaterial; radius: number; key: string }

export class TileLayer {
  private context: Composite
  private detail: Composite
  private cache = new Map<string, HTMLImageElement>()
  private loadSeq = 0
  private status: TileStatus = { zoom: 0, detailZoom: 0, tiles: 0, resolutionM: 0, state: 'idle', attribution: ATTRIB }
  private enabled = false
  private lastKey = ''

  constructor() {
    // Just above the globe surface (GLOBE_R=2); must stay inside the camera's
    // closest approach so tiles are never behind the camera.
    this.context = this.makeComposite(GLOBE_R * 1.003)
    this.detail = this.makeComposite(GLOBE_R * 1.006)
  }

  private makeComposite(radius: number): Composite {
    const material = new THREE.MeshBasicMaterial({ transparent: true, opacity: 1, depthWrite: false, side: THREE.FrontSide })
    const mesh = new THREE.Mesh(new THREE.BufferGeometry(), material)
    mesh.renderOrder = 2.5
    mesh.visible = false
    return { mesh, material, radius, key: '' }
  }

  getMeshes(): THREE.Mesh[] { return [this.context.mesh, this.detail.mesh] }

  setEnabled(v: boolean): void {
    this.enabled = v
    if (!v) { this.context.mesh.visible = false; this.detail.mesh.visible = false }
  }

  getStatus(): TileStatus { return { ...this.status } }

  update(centerLon: number, centerLat: number, distance: number): void {
    if (!this.enabled) return
    const ctxZoom = distance > 8 ? 5 : distance > 4 ? 8 : distance > 1.5 ? 10 : distance > 0.3 ? 11 : 12
    const detZoom = distance > 8 ? 6 : distance > 4 ? 9 : distance > 1.5 ? 12 : distance > 0.3 ? 14 : MAX_ZOOM
    const ctxN = 5, detN = 3
    const key = `${ctxZoom}/${detZoom}/${lon2tile(centerLon, ctxZoom)}/${lat2tile(centerLat, ctxZoom)}`
    if (key === this.lastKey) return
    this.lastKey = key
    void this.load(centerLon, centerLat, ctxZoom, ctxN, detZoom, detN)
  }

  private async load(centerLon: number, centerLat: number,
                     cz: number, cn: number, dz: number, dn: number): Promise<void> {
    const seq = ++this.loadSeq
    this.status = { zoom: cz, detailZoom: dz, tiles: 0,
                    resolutionM: resolution(dz, centerLat), state: 'loading', attribution: ATTRIB }
    const ctxKeys = this.tileKeys(centerLon, centerLat, cz, cn)
    const detKeys = this.tileKeys(centerLon, centerLat, dz, dn)
    this.status.tiles = ctxKeys.length + detKeys.length
    const ctxImgs = await this.loadMany(ctxKeys)
    if (seq !== this.loadSeq) return
    const detImgs = await this.loadMany(detKeys)
    if (seq !== this.loadSeq) return
    if (!ctxImgs.some(Boolean) && !detImgs.some(Boolean)) { this.status.state = 'error'; return }

    if (ctxImgs.some(Boolean)) this.apply(this.context, centerLon, centerLat, cz, cn, ctxImgs, false)
    else this.context.mesh.visible = false
    if (detImgs.some(Boolean)) this.apply(this.detail, centerLon, centerLat, dz, dn, detImgs, true)
    else this.detail.mesh.visible = false
    this.status.state = 'ready'
  }

  private tileKeys(lon: number, lat: number, z: number, n: number): TileKey[] {
    const cx = lon2tile(lon, z), cy = lat2tile(lat, z), half = Math.floor(n / 2), keys: TileKey[] = []
    for (let dy = -half; dy <= half; dy++) for (let dx = -half; dx <= half; dx++) {
      const x = cx + dx, y = cy + dy, max = Math.pow(2, z)
      if (x >= 0 && y >= 0 && x < max && y < max) keys.push({ z, x, y })
    }
    return keys
  }

  private async loadMany(keys: TileKey[]): Promise<Array<HTMLImageElement | null>> {
    const out: Array<HTMLImageElement | null> = new Array(keys.length).fill(null)
    let cursor = 0
    const worker = async () => { while (cursor < keys.length) { const i = cursor++; out[i] = await this.getTile(keys[i]) } }
    await Promise.all([worker(), worker(), worker()])
    return out
  }

  private apply(c: Composite, lon: number, lat: number, z: number, n: number,
                imgs: Array<HTMLImageElement | null>, feather: boolean): void {
    const cx = lon2tile(lon, z), cy = lat2tile(lat, z), half = Math.floor(n / 2)
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = n * TILE_SIZE
    const ctx = canvas.getContext('2d')!
    let i = 0
    for (const k of this.tileKeys(lon, lat, z, n)) {
      const img = imgs[i++]
      const col = k.x - (cx - half), row = k.y - (cy - half)
      if (img) ctx.drawImage(img, col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
    }
    // Feather both layers: context fades gently, detail fades a bit earlier
    // so it blends into the context layer underneath.
    {
      const W = canvas.width, H = canvas.height
      const inner = feather ? 0.32 : 0.42
      const outer = feather ? 0.74 : 0.88
      const g = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * inner,
                                         W / 2, H / 2, Math.max(W, H) * outer)
      g.addColorStop(0, 'rgba(0,0,0,1)')
      g.addColorStop(0.74, 'rgba(0,0,0,1)')
      g.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.globalCompositeOperation = 'destination-in'
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H)
      ctx.globalCompositeOperation = 'source-over'
    }
    const tex = new THREE.CanvasTexture(canvas)
    tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8
    const west = tile2lon(cx - half, z), east = tile2lon(cx - half + n, z)
    const north = tile2lat(cy - half, z), south = tile2lat(cy - half + n, z)
    c.mesh.geometry.dispose()
    c.mesh.geometry = patchGeometry(west, east, south, north, c.radius)
    c.material.map?.dispose(); c.material.map = tex; c.material.needsUpdate = true
    c.mesh.visible = true
  }

  private getTile(k: TileKey, retry = 1): Promise<HTMLImageElement | null> {
    const ck = keyOf(k)
    const cached = this.cache.get(ck)
    if (cached?.complete) return Promise.resolve(cached)
    return new Promise(resolve => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => {
        this.cache.set(ck, img)
        if (this.cache.size > 200) { const f = this.cache.keys().next().value; if (f) this.cache.delete(f) }
        resolve(img)
      }
      img.onerror = () => {
        if (retry > 0) {
          const i2 = new Image(); i2.crossOrigin = 'anonymous'
          i2.onload = () => { this.cache.set(ck, i2); resolve(i2) }
          i2.onerror = () => resolve(null)
          i2.src = TILE_URL(k.z, k.y, k.x) + `?r=${Date.now()}`
        } else resolve(null)
      }
      img.src = TILE_URL(k.z, k.y, k.x)
    })
  }

  dispose(): void {
    for (const c of [this.context, this.detail]) {
      c.mesh.geometry.dispose(); c.material.map?.dispose(); c.material.dispose()
    }
    this.cache.clear()
  }
}
