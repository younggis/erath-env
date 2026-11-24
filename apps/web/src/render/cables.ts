/** TeleGeography submarine cables (glowing curves) and landing nodes. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'
import { resampleLine } from './cableGeometry'

interface GeoFeature {
  geometry?: { type?: string; coordinates?: any }
  properties?: Record<string, any>
}

const LANDING_VERT = /* glsl */`
void main(){
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = 5.0;
}`
const LANDING_FRAG = /* glsl */`
precision highp float;
out vec4 f;
void main(){
  float d = length(gl_PointCoord * 2.0 - 1.0);
  if (d > 1.0) discard;
  f = vec4(1.0, 0.75, 0.35, 1.0 - smoothstep(0.2, 1.0, d));
}`

export class CableLayer {
  readonly lines: THREE.LineSegments
  readonly landings: THREE.Points
  private lineMat: THREE.LineBasicMaterial
  private landingMat: THREE.ShaderMaterial
  private hasData = false
  private wanted = false

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    this.lineMat = new THREE.LineBasicMaterial({
      color: 0x4fe0ff, transparent: true, opacity: 0.6,
      depthWrite: false, blending: THREE.AdditiveBlending,
    })
    this.lines = new THREE.LineSegments(geo, this.lineMat)
    this.lines.renderOrder = 3
    this.lines.frustumCulled = false
    this.lines.visible = false

    const lgeo = new THREE.BufferGeometry()
    lgeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    this.landingMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: LANDING_VERT, fragmentShader: LANDING_FRAG,
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.landings = new THREE.Points(lgeo, this.landingMat)
    this.landings.renderOrder = 4
    this.landings.frustumCulled = false
    this.landings.visible = false
  }

  setData(cables: GeoFeature[] = [], landings: GeoFeature[] = []): void {
    const segments: number[] = []
    const MAX_FEATURES = 420
    for (const feature of cables.slice(0, MAX_FEATURES)) {
      const g = feature.geometry || {}
      const lines: number[][][] = g.type === 'LineString' ? [g.coordinates || []]
        : g.type === 'MultiLineString' ? (g.coordinates || []) : []
      for (const coords of lines) {
        const pts = resampleLine(coords, 1.5)
        for (let i = 1; i < pts.length; i++) {
          const a = ll2xyz(pts[i - 1].lon, pts[i - 1].lat, GLOBE_R * 1.004)
          const b = ll2xyz(pts[i].lon, pts[i].lat, GLOBE_R * 1.004)
          segments.push(a.x, a.y, a.z, b.x, b.y, b.z)
        }
      }
    }
    const nodes: number[] = []
    for (const feature of landings) {
      const c = feature.geometry?.coordinates
      if (!Array.isArray(c) || c.length < 2) continue
      const p = ll2xyz(Number(c[0]), Number(c[1]), GLOBE_R * 1.006)
      nodes.push(p.x, p.y, p.z)
    }
    this.lines.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(segments), 3))
    this.landings.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(nodes), 3))
    this.hasData = segments.length > 0 || nodes.length > 0
    this.setVisible(this.wanted)
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.lines.visible = v && this.hasData && this.lines.geometry.getAttribute('position').count > 0
    this.landings.visible = v && this.hasData && this.landings.geometry.getAttribute('position').count > 0
  }

  dispose(): void {
    this.lines.geometry.dispose(); this.lineMat.dispose()
    this.landings.geometry.dispose(); this.landingMat.dispose()
  }
}
