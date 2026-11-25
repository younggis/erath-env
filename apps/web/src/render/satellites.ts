/** CelesTrak satellite layer: SGP4 positions, orbit rings and FOV footprints. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'
import {
  footprintAngle, orbitRing, propagateSatrec, satrecFromTle,
  type SatPosition, type TleRecord,
} from './satelliteOrbit'

const EARTH_KM = 6371
const MAX_SATS = 180
const ORBIT_GROUPS = new Set(['stations', 'weather'])

const POINT_VERT = /* glsl */`
void main(){
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = 6.0;
}`
const POINT_FRAG = /* glsl */`
precision highp float;
out vec4 f;
void main(){
  float d = length(gl_PointCoord * 2.0 - 1.0);
  if (d > 1.0) discard;
  f = vec4(vec3(0.65, 0.95, 1.0), 1.0 - smoothstep(0.2, 1.0, d));
}`

function satRadius(altKm: number): number {
  return GLOBE_R * (1 + Math.max(0, altKm) / EARTH_KM)
}

/** Destination point on a sphere given bearing and central angle (radians). */
function destination(latDeg: number, lonDeg: number, bearing: number,
                     angle: number): [number, number] {
  const la = latDeg * Math.PI / 180
  const lo = lonDeg * Math.PI / 180
  const sinLa = Math.sin(la) * Math.cos(angle) + Math.cos(la) * Math.sin(angle) * Math.cos(bearing)
  const lat2 = Math.asin(Math.max(-1, Math.min(1, sinLa)))
  const lon2 = lo + Math.atan2(Math.sin(bearing) * Math.sin(angle) * Math.cos(la),
                               Math.cos(angle) - Math.sin(la) * sinLa)
  return [lon2 * 180 / Math.PI, lat2 * 180 / Math.PI]
}

export class SatelliteLayer {
  readonly points: THREE.Points
  readonly orbits: THREE.LineSegments
  readonly footprints: THREE.LineSegments
  private pointMat: THREE.ShaderMaterial
  private orbitMat: THREE.LineBasicMaterial
  private fovMat: THREE.LineBasicMaterial
  private tles: TleRecord[] = []
  private satrecs: ReturnType<typeof satrecFromTle>[] = []
  private lastUpdate = 0

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    this.pointMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: POINT_VERT, fragmentShader: POINT_FRAG,
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.points = new THREE.Points(geo, this.pointMat)
    this.points.renderOrder = 7
    this.points.frustumCulled = false
    this.points.visible = false

    this.orbitMat = new THREE.LineBasicMaterial({
      color: 0x5fd0ff, transparent: true, opacity: 0.35, depthWrite: false,
    })
    this.orbits = new THREE.LineSegments(new THREE.BufferGeometry(), this.orbitMat)
    this.orbits.frustumCulled = false
    this.orbits.visible = false

    this.fovMat = new THREE.LineBasicMaterial({
      color: 0xffd27f, transparent: true, opacity: 0.45, depthWrite: false,
    })
    this.footprints = new THREE.LineSegments(new THREE.BufferGeometry(), this.fovMat)
    this.footprints.frustumCulled = false
    this.footprints.visible = false
  }

  private wanted = false

  setTles(tles: TleRecord[]): void {
    this.tles = tles.slice(0, MAX_SATS)
    this.satrecs = this.tles.map(t => satrecFromTle(t.line1, t.line2))
    this.lastUpdate = 0
    // TLEs often arrive after the toggle was enabled — re-apply visibility.
    this.setVisible(this.wanted)
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    const has = this.tles.length > 0
    this.points.visible = v && has
    this.orbits.visible = v && has
    this.footprints.visible = v && has
  }

  update(nowMs: number): void {
    if (!this.points.visible || !this.tles.length) return
    if (nowMs - this.lastUpdate < 500) return  // throttle SGP4 propagation
    this.lastUpdate = nowMs
    const date = new Date(nowMs)

    const positions: number[] = []
    const orbitPositions: number[] = []
    const fovPositions: number[] = []
    for (let idx = 0; idx < this.tles.length; idx++) {
      const tle = this.tles[idx]
      const satrec = this.satrecs[idx]
      const pos: SatPosition | null = satrec
        ? propagateSatrec(satrec, date)
        : null
      if (!pos) continue
      const p = ll2xyz(pos.lon, pos.lat, satRadius(pos.altKm))
      positions.push(p.x, p.y, p.z)

      if (!ORBIT_GROUPS.has(tle.group)) continue
      const ring = orbitRing(tle.line1, tle.line2, date, 48, 125)
      for (let i = 1; i < ring.length; i++) {
        const a = ll2xyz(ring[i - 1].lon, ring[i - 1].lat, satRadius(ring[i - 1].altKm))
        const b = ll2xyz(ring[i].lon, ring[i].lat, satRadius(ring[i].altKm))
        orbitPositions.push(a.x, a.y, a.z, b.x, b.y, b.z)
      }
      if (pos.altKm > 200) {
        const angle = footprintAngle(pos.altKm)
        const steps = 48
        let prev = ll2xyz(...destination(pos.lat, pos.lon, 0, angle), GLOBE_R * 1.01)
        for (let i = 1; i <= steps; i++) {
          const [lon, lat] = destination(pos.lat, pos.lon, i / steps * Math.PI * 2, angle)
          const cur = ll2xyz(lon, lat, GLOBE_R * 1.01)
          fovPositions.push(prev.x, prev.y, prev.z, cur.x, cur.y, cur.z)
          prev = cur
        }
      }
    }

    this.points.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3))
    this.orbits.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(orbitPositions), 3))
    this.footprints.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(fovPositions), 3))
  }

  dispose(): void {
    this.points.geometry.dispose(); this.pointMat.dispose()
    this.orbits.geometry.dispose(); this.orbitMat.dispose()
    this.footprints.geometry.dispose(); this.fovMat.dispose()
  }
}
