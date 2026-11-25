/** NOAA NDBC buoy markers: one point per active ocean station. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'

const VERT = /* glsl */`
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = 9.0 * (7.0 / -mv.z);
}`

const FRAG = /* glsl */`
precision highp float;
out vec4 f;
void main(){
  vec2 q = gl_PointCoord * 2.0 - 1.0;
  float d = length(q);
  if (d > 1.0) discard;
  float ring = smoothstep(0.55, 0.75, d) * (1.0 - smoothstep(0.9, 1.0, d));
  float core = 1.0 - smoothstep(0.0, 0.45, d);
  f = vec4(vec3(0.36, 0.85, 1.0) * (0.6 + 0.8 * ring), 0.45 * core + 0.85 * ring);
}`

export interface BuoyPoint {
  station_id: string
  lon: number
  lat: number
  observed_at: string
  values: Record<string, number | null>
}

export class BuoyLayer {
  readonly points: THREE.Points
  private material: THREE.ShaderMaterial
  private wanted = false

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.points = new THREE.Points(geo, this.material)
    this.points.renderOrder = 5
    this.points.frustumCulled = false
    this.points.visible = false
  }

  setBuoys(buoys: BuoyPoint[]): void {
    const positions = new Float32Array(buoys.length * 3)
    buoys.forEach((b, i) => {
      const p = ll2xyz(b.lon, b.lat, GLOBE_R * 1.025)
      positions[i * 3] = p.x; positions[i * 3 + 1] = p.y; positions[i * 3 + 2] = p.z
    })
    this.points.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    this.setVisible(this.wanted)
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.points.visible = v && this.points.geometry.getAttribute('position').count > 0
  }

  dispose(): void {
    this.points.geometry.dispose()
    this.material.dispose()
  }
}
