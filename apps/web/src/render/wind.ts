/** Wind particle layer with real trails, driven by an independent wind source. */
import * as THREE from 'three'
import { ll2xyz, GLOBE_R, sampleGrid } from './geo'
import { rgbFor, speedOf } from './palette'
import type { WindData } from './types'

const TRAIL = 12

interface Particle {
  lon: number
  lat: number
  trail: Array<[number, number]>
  age: number
  maxAge: number
}

export class WindLayer {
  readonly lines: THREE.LineSegments
  private particles: Particle[] = []
  private posAttr: THREE.BufferAttribute
  private colAttr: THREE.BufferAttribute
  private data: WindData | null = null
  private count = 0
  private speed = 1
  private hasSource = false
  private radius: number

  constructor(count = 4000, radius = GLOBE_R * 1.048) {
    this.count = count
    this.radius = radius
    const segments = count * (TRAIL - 1)
    const positions = new Float32Array(segments * 2 * 3)
    const colors = new Float32Array(segments * 2 * 3)
    const g = new THREE.BufferGeometry()
    this.posAttr = new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage)
    this.colAttr = new THREE.BufferAttribute(colors, 3).setUsage(THREE.DynamicDrawUsage)
    g.setAttribute('position', this.posAttr)
    g.setAttribute('color', this.colAttr)
    this.lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false,
    }))
    this.lines.renderOrder = 4
    this.lines.frustumCulled = false
    this.reset()
  }

  private spawn(): Particle {
    const lon = Math.random() * 360 - 180
    // Uniform distribution on the sphere.
    const lat = THREE.MathUtils.radToDeg(Math.asin(2 * Math.random() - 1))
    return { lon, lat, trail: [], age: Math.random() * 60, maxAge: 50 + Math.random() * 90 }
  }

  reset(): void {
    this.particles = Array.from({ length: this.count }, () => this.spawn())
  }

  setCount(n: number): void {
    if (n === this.count) return
    this.count = n
    const segments = n * (TRAIL - 1)
    // Replace the attributes entirely: swapping only .array leaves the GPU
    // buffer bound to the old size and nothing renders.
    this.posAttr = new THREE.BufferAttribute(new Float32Array(segments * 2 * 3), 3).setUsage(THREE.DynamicDrawUsage)
    this.colAttr = new THREE.BufferAttribute(new Float32Array(segments * 2 * 3), 3).setUsage(THREE.DynamicDrawUsage)
    this.lines.geometry.setAttribute('position', this.posAttr)
    this.lines.geometry.setAttribute('color', this.colAttr)
    this.reset()
  }

  setWind(data: WindData | null): void {
    this.data = data
    this.hasSource = !!data
    if (!data) {
      // Do NOT fabricate a wind field. Clear all trails so the user sees the
      // honest absence of data instead of a misleading synthetic flow.
      for (const p of this.particles) p.trail = []
      this.lines.visible = false
    } else {
      this.lines.visible = true
    }
  }

  hasWindSource(): boolean { return this.hasSource }

  setSpeed(s: number): void { this.speed = s }
  setVisible(v: boolean): void { this.lines.visible = v && this.hasSource }

  update(dtSeconds: number): void {
    if (!this.hasSource || !this.lines.visible) return
    const pos = this.posAttr.array as Float32Array
    const col = this.colAttr.array as Float32Array
    const scale = 4200 * this.speed
    let write = 0

    for (const p of this.particles) {
      let u = 0; let v = 0
      const s = sampleGrid(this.data!.values, this.data!.grid, this.data!.ncomp, p.lon, p.lat)
      if (Number.isFinite(s[0]) && Number.isFinite(s[1])) { u = s[0]; v = s[1] }
      else { // inside a data hole: recycle immediately
        Object.assign(p, this.spawn())
        p.age = 0
        continue
      }
      const cosLat = Math.max(0.08, Math.cos(THREE.MathUtils.degToRad(p.lat)))
      p.lon += (u * dtSeconds * scale) / (111320 * cosLat) * 180 / Math.PI
      p.lat += (v * dtSeconds * scale) / 111320 * 180 / Math.PI
      if (p.lon > 180) p.lon -= 360
      if (p.lon < -180) p.lon += 360
      if (p.lat > 89) p.lat = 89
      if (p.lat < -89) p.lat = -89
      p.trail.push([p.lon, p.lat])
      if (p.trail.length > TRAIL) p.trail.shift()
      p.age += dtSeconds * 2

      if (p.age > p.maxAge || p.lat >= 89 || p.lat <= -89) {
        const fresh = this.spawn()
        p.lon = fresh.lon; p.lat = fresh.lat; p.trail = []; p.age = 0
      }

      const sp = speedOf(u, v)
      const base = rgbFor('wind', sp, [0, 30])
      for (let t = 1; t < p.trail.length; t++) {
        const a = ll2xyz(p.trail[t - 1][0], p.trail[t - 1][1], this.radius)
        const b = ll2xyz(p.trail[t][0], p.trail[t][1], this.radius)
        const fade = 0.5 + 0.5 * (t / p.trail.length)
        pos[write] = a.x; pos[write + 1] = a.y; pos[write + 2] = a.z; write += 3
        pos[write] = b.x; pos[write + 1] = b.y; pos[write + 2] = b.z; write += 3
        // Vertex colours must be in 0..1 (rgbFor returns 0..255). Boost a
        // little so trails stay visible against the dark globe.
        const boost = 2.2
        col[write - 6] = (base[0] / 255) * fade * boost
        col[write - 5] = (base[1] / 255) * fade * boost
        col[write - 4] = (base[2] / 255) * fade * boost
        col[write - 3] = (base[0] / 255) * fade * boost
        col[write - 2] = (base[1] / 255) * fade * boost
        col[write - 1] = (base[2] / 255) * fade * boost
      }
    }
    // Zero out unused vertices.
    pos.fill(0, write)
    col.fill(0, write)
    this.posAttr.needsUpdate = true
    this.colAttr.needsUpdate = true
  }

  get particleCount(): number { return this.count }

  dispose(): void {
    this.lines.geometry.dispose()
    ;(this.lines.material as THREE.Material).dispose()
  }
}
