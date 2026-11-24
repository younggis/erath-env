/** Solar-wind particle stream flowing from the Sun toward the magnetosphere.
 *  Particle positions are computed in the vertex shader from per-particle
 *  seeds, so the CPU only updates a handful of uniforms each frame.
 */
import * as THREE from 'three'
import { GLOBE_R } from './geo'
import type { SolarWindData } from '../realtime'

const VERT = `
attribute vec4 aSeed;   // phase, lateralX, lateralY, speedFactor
uniform float uTime;
uniform float uSpeed;
uniform float uBz;
uniform float uSize;
uniform vec3 uSunDir;
varying float vHeat;
varying float vPhase;
void main(){
  float phase = fract(aSeed.x + uTime * 0.035 * (uSpeed/400.0) * (0.6+aSeed.w*0.8));
  vPhase = phase;
  // Travel from 3.2 R on the sunward side down to the magnetopause.
  float startR = 2.3, endR = 1.14;
  float rr = mix(startR, endR, phase);
  vec3 axis = normalize(uSunDir);
  vec3 right = normalize(cross(axis, vec3(0.0,1.0,0.0)) + vec3(0.0001));
  vec3 up = normalize(cross(right, axis));
  float spread = (1.0 - phase) * 0.75;
  vec3 p = axis * rr + right * aSeed.y * spread + up * aSeed.z * spread;
  // Southward Bz opens the magnetosphere: particles funnel toward the poles.
  float south = clamp((-uBz)/8.0, 0.0, 1.0);
  float polar = smoothstep(0.7, 1.0, phase) * south;
  p += up * polar * sign(aSeed.z) * rr * 0.45;
  vHeat = clamp((uSpeed-250.0)/900.0, 0.0, 1.0) * 0.6 + south*0.4 + aSeed.w*0.15;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = uSize * (1.0 - phase * 0.45) * (4.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}`

const FRAG = `
precision highp float;
varying float vHeat;
varying float vPhase;
void main(){
  vec2 p = gl_PointCoord*2.0-1.0;
  float r = length(p);
  if(r>1.0) discard;
  float core = exp(-r*r*16.0);
  float halo = exp(-r*r*4.0)*0.4;
  float a = (core + halo) * (0.25 + 0.75*(1.0-vPhase)) * 0.28;
  vec3 slow = vec3(0.25, 0.85, 1.0);
  vec3 fast = vec3(1.0, 0.35, 0.75);
  vec3 col = mix(slow, fast, clamp(vHeat,0.0,1.0));
  gl_FragColor = vec4(col*(0.5+core*0.9), clamp(a,0.0,0.9));
}`

const COUNT = 900

export class SolarWindLayer {
  readonly points: THREE.Points
  private material: THREE.ShaderMaterial
  private sunDir = new THREE.Vector3(1, 0, 0)

  constructor() {
    const seeds = new Float32Array(COUNT * 4)
    for (let i = 0; i < COUNT; i++) {
      seeds[i * 4] = Math.random()                       // phase
      const a = Math.random() * Math.PI * 2
      const rad = Math.sqrt(Math.random())
      seeds[i * 4 + 1] = Math.cos(a) * rad               // lateral X
      seeds[i * 4 + 2] = Math.sin(a) * rad               // lateral Y
      seeds[i * 4 + 3] = Math.random()                   // speed factor
    }
    const geo = new THREE.BufferGeometry()
    // Dummy positions; real position is derived in the vertex shader.
    geo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(COUNT * 3), 3))
    geo.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 4))
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 5)
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: {
        uTime: { value: 0 }, uSpeed: { value: 400 }, uBz: { value: 0 },
        uSize: { value: 5 }, uSunDir: { value: this.sunDir },
      },
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    })
    this.points = new THREE.Points(geo, this.material)
    this.points.renderOrder = 4
    this.points.frustumCulled = false
    this.points.visible = false
  }

  setData(data: SolarWindData | null): void {
    if (!data) { this.points.visible = false; return }
    this.material.uniforms.uSpeed.value = Number(data.speed_kms) || 400
    this.material.uniforms.uBz.value = Number(data.bz_gsm) || 0
    this.material.uniforms.uTime.value = 0
  }

  setSunDirection(v: THREE.Vector3): void { this.sunDir.copy(v).normalize() }
  update(time: number): void { this.material.uniforms.uTime.value = time }
  setVisible(v: boolean): void { this.points.visible = v }
  dispose(): void { this.points.geometry.dispose(); this.material.dispose() }
}
