/** Blitzortung lightning layer: a bright flash followed by an expanding,
 *  fading ripple. Additive over the cloud volume so strikes read as a
 *  momentary illumination of the night-side cloud deck. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'

const VERT = /* glsl */`
precision highp float;
in float aTime;
uniform float uNow;
out float vAge;
out float vFade;
void main(){
  float age = uNow - aTime;
  vAge = max(0.0, age);
  vFade = (age >= 0.0 && age < 2.8) ? (1.0 - age / 2.8) : 0.0;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = (7.0 + 30.0 * min(age, 1.4)) * (4.0 / max(0.75, -mv.z));
}`

const FRAG = /* glsl */`
precision highp float;
in float vAge;
in float vFade;
out vec4 f;
void main(){
  float d = length(gl_PointCoord * 2.0 - 1.0);
  if (d > 1.0) discard;
  float spark = exp(-d * d * 24.0) * (1.0 - smoothstep(0.0, 0.35, vAge));
  float x = (d - vAge * 0.42) * 15.0;
  float ring = exp(-x * x) * (1.0 - smoothstep(0.2, 2.4, vAge));
  float a = (spark + 0.55 * ring) * vFade;
  if (a < 0.012) discard;
  vec3 col = vec3(0.62, 0.80, 1.0) * (spark * 2.0 + ring);
  f = vec4(col, min(1.0, a));
}`

export interface LightningStrike {
  id: string
  lon: number
  lat: number
  observed_at: string
  magnitude?: number | null
}

export class LightningLayer {
  readonly points: THREE.Points
  private material: THREE.ShaderMaterial
  private uniforms = { uNow: { value: Date.now() / 1000 } }

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    geo.setAttribute('aTime', new THREE.BufferAttribute(new Float32Array(0), 1))
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      uniforms: this.uniforms,
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.points = new THREE.Points(geo, this.material)
    this.points.renderOrder = 6
    this.points.frustumCulled = false
    this.points.visible = false
  }

  setStrikes(strikes: LightningStrike[]): void {
    const positions = new Float32Array(strikes.length * 3)
    const times = new Float32Array(strikes.length)
    strikes.forEach((s, i) => {
      const p = ll2xyz(s.lon, s.lat, GLOBE_R * 1.03)
      positions[i * 3] = p.x; positions[i * 3 + 1] = p.y; positions[i * 3 + 2] = p.z
      times[i] = Date.parse(s.observed_at) / 1000
    })
    this.points.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    this.points.geometry.setAttribute('aTime', new THREE.BufferAttribute(times, 1))
  }

  setVisible(v: boolean): void { this.points.visible = v }

  update(): void { this.uniforms.uNow.value = Date.now() / 1000 }

  dispose(): void {
    this.points.geometry.dispose()
    this.material.dispose()
  }
}
