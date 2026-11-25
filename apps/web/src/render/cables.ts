/** TeleGeography submarine cables: flowing data pulses + landing nodes. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'
import { resampleLine, type LonLat } from './cableGeometry'

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

const VERT = /* glsl */`
in float aProgress;
in float aCable;
uniform float uTime;
out float vGlow;
void main(){
  float head = fract(uTime * 0.13 + aCable * 0.137);
  float d = abs(aProgress - head);
  d = min(d, 1.0 - d);
  vGlow = exp(-d * d * 900.0);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`

const FRAG = /* glsl */`
precision highp float;
in float vGlow;
out vec4 f;
void main(){
  vec3 base = vec3(0.10, 0.48, 0.66);
  vec3 hot = vec3(0.75, 0.98, 1.0);
  vec3 col = mix(base, hot, vGlow);
  float a = 0.22 + 0.70 * vGlow;
  f = vec4(col * (0.28 + 1.10 * vGlow), a);
}`

/** Angular distance along a resampled cable, normalised to 0..1. */
function progressAlong(points: LonLat[]): number[] {
  const dist = [0]
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i]
    const la = a.lat * Math.PI / 180, lb = b.lat * Math.PI / 180
    const dl = (b.lon - a.lon) * Math.PI / 180
    const ang = Math.acos(Math.max(-1, Math.min(1,
      Math.sin(la) * Math.sin(lb) + Math.cos(la) * Math.cos(lb) * Math.cos(dl))))
    dist.push(dist[i - 1] + ang)
  }
  const total = dist[dist.length - 1] || 1
  return dist.map(d => d / total)
}

export class CableLayer {
  readonly lines: THREE.LineSegments
  readonly landings: THREE.Points
  private lineMat: THREE.ShaderMaterial
  private landingMat: THREE.ShaderMaterial
  private hasData = false
  private wanted = false

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    geo.setAttribute('aProgress', new THREE.BufferAttribute(new Float32Array(0), 1))
    geo.setAttribute('aCable', new THREE.BufferAttribute(new Float32Array(0), 1))
    this.lineMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 } },
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
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
    const progress: number[] = []
    const cableIdx: number[] = []
    const MAX_FEATURES = 420
    cables.slice(0, MAX_FEATURES).forEach((feature, fi) => {
      const g = feature.geometry || {}
      const lines: number[][][] = g.type === 'LineString' ? [g.coordinates || []]
        : g.type === 'MultiLineString' ? (g.coordinates || []) : []
      for (const coords of lines) {
        const pts = resampleLine(coords, 1.5)
        if (pts.length < 2) continue
        const pg = progressAlong(pts)
        for (let i = 1; i < pts.length; i++) {
          const a = ll2xyz(pts[i - 1].lon, pts[i - 1].lat, GLOBE_R * 1.004)
          const b = ll2xyz(pts[i].lon, pts[i].lat, GLOBE_R * 1.004)
          segments.push(a.x, a.y, a.z, b.x, b.y, b.z)
          progress.push(pg[i - 1], pg[i])
          cableIdx.push(fi, fi)
        }
      }
    })
    const nodes: number[] = []
    for (const feature of landings) {
      const c = feature.geometry?.coordinates
      if (!Array.isArray(c) || c.length < 2) continue
      const p = ll2xyz(Number(c[0]), Number(c[1]), GLOBE_R * 1.006)
      nodes.push(p.x, p.y, p.z)
    }
    const geo = this.lines.geometry
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(segments), 3))
    geo.setAttribute('aProgress', new THREE.BufferAttribute(new Float32Array(progress), 1))
    geo.setAttribute('aCable', new THREE.BufferAttribute(new Float32Array(cableIdx), 1))
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

  update(seconds: number): void { this.lineMat.uniforms.uTime.value = seconds }

  dispose(): void {
    this.lines.geometry.dispose(); this.lineMat.dispose()
    this.landings.geometry.dispose(); this.landingMat.dispose()
  }
}
