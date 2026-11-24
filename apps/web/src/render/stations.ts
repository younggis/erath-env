/** Station markers: shader-based glowing rings with pulse (Shadertoy style). */
import * as THREE from 'three'
import { ll2xyz, GLOBE_R } from './geo'
import type { StationPoint } from './types'

const R = GLOBE_R * 1.024

const VERT = `
attribute vec3 aColor;
varying vec3 vColor;
uniform float uTime;
uniform float uSize;
void main(){
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  // gentle per-station pulse
  float pulse = 0.9 + 0.1 * sin(uTime * 2.0 + position.x * 30.0);
  gl_PointSize = uSize * pulse * (8.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}`

const FRAG = `
varying vec3 vColor;
void main(){
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float r = length(p);
  // glowing ring + bright core
  float ring = smoothstep(0.42, 0.30, r) - smoothstep(0.30, 0.18, r);
  float core = exp(-r * r * 30.0);
  float halo = exp(-r * r * 4.0) * 0.35;
  float a = clamp(ring + core + halo, 0.0, 1.0);
  if (a < 0.02) discard;
  vec3 c = vColor * (0.4 + core * 0.6 + ring * 0.3);
  gl_FragColor = vec4(c, a * 0.75);
}`

export class StationLayer {
  readonly points: THREE.Points
  private material: THREE.ShaderMaterial
  private stations: StationPoint[] = []
  private raycaster = new THREE.Raycaster()

  constructor() {
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 }, uSize: { value: 16 } },
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    })
    this.points = new THREE.Points(new THREE.BufferGeometry(), this.material)
    this.points.renderOrder = 6
    this.raycaster.params.Points = { threshold: 0.06 }
  }

  setStations(stations: StationPoint[]): void {
    this.stations = stations
    const pos: number[] = []
    const col: number[] = []
    for (const s of stations) {
      const p = ll2xyz(s.lon, s.lat, R)
      pos.push(p.x, p.y, p.z)
      // Colour by temperature: cold=cyan, warm=amber. Missing=teal.
      if (typeof s.tempC === 'number') {
        const t = THREE.MathUtils.clamp((s.tempC + 20) / 45, 0, 1)
        col.push(0.2 + t * 0.8, 0.7 + t * 0.25, 1.0 - t * 0.6)
      } else {
        col.push(0.4, 1.0, 0.8)
      }
    }
    const g = this.points.geometry
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('aColor', new THREE.Float32BufferAttribute(col, 3))
    g.computeBoundingSphere()
  }

  update(time: number): void { this.material.uniforms.uTime.value = time }

  pick(ndc: THREE.Vector2, camera: THREE.Camera): StationPoint | null {
    if (!this.stations.length) return null
    this.raycaster.setFromCamera(ndc, camera)
    const hits = this.raycaster.intersectObject(this.points, false)
    if (!hits.length) return null
    const idx = hits[0].index
    return idx !== undefined ? this.stations[idx] || null : null
  }

  setVisible(v: boolean): void { this.points.visible = v }

  dispose(): void {
    this.points.geometry.dispose()
    this.material.dispose()
  }
}
