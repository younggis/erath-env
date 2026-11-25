/** Animated great-circle flight-route arcs with flowing light pulses. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'
import { sampleArc } from './greatCircle'

const VERT = /* glsl */`
in float aProgress;
in float aRoute;
uniform float uTime;
uniform float uMaxRoutes;
out float vGlow;
void main(){
  if (aRoute > uMaxRoutes) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    vGlow = 0.0;
    return;
  }
  float head = fract(uTime * 0.20 + aRoute * 0.137);
  float d = abs(aProgress - head);
  d = min(d, 1.0 - d);
  vGlow = exp(-d * d * 700.0);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`

const FRAG = /* glsl */`
precision highp float;
in float vGlow;
out vec4 f;
void main(){
  vec3 base = vec3(0.12, 0.48, 0.92);
  vec3 hot = vec3(0.70, 0.96, 1.0);
  vec3 col = mix(base, hot, vGlow);
  float a = 0.14 + 0.80 * vGlow;
  f = vec4(col * (0.35 + 1.4 * vGlow), a);
}`

export interface RouteAirport {
  lon: number
  lat: number
  name?: string
}

export class RouteArcLayer {
  readonly lines: THREE.LineSegments
  private material: THREE.ShaderMaterial
  private wanted = false
  private hasData = false
  private totalRoutes = 0
  private density = 1

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    geo.setAttribute('aProgress', new THREE.BufferAttribute(new Float32Array(0), 1))
    geo.setAttribute('aRoute', new THREE.BufferAttribute(new Float32Array(0), 1))
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 }, uMaxRoutes: { value: 4000 } },
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.lines = new THREE.LineSegments(geo, this.material)
    this.lines.renderOrder = 4
    this.lines.frustumCulled = false
    this.lines.visible = false
  }

  setData(airports: Record<string, RouteAirport>, routes: string[][]): void {
    const positions: number[] = []
    const progress: number[] = []
    const routeIdx: number[] = []
    const SEG = 18
    routes.forEach((pair, ri) => {
      const a = airports[pair[0]], b = airports[pair[1]]
      if (!a || !b) return
      const pts = sampleArc(a, b, SEG)
      for (let i = 1; i < pts.length; i++) {
        const p0 = ll2xyz(pts[i - 1].lon, pts[i - 1].lat, GLOBE_R * (1 + pts[i - 1].h))
        const p1 = ll2xyz(pts[i].lon, pts[i].lat, GLOBE_R * (1 + pts[i].h))
        positions.push(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
        progress.push(pts[i - 1].progress, pts[i].progress)
        routeIdx.push(ri, ri)
      }
    })
    this.lines.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3))
    this.lines.geometry.setAttribute('aProgress',
      new THREE.BufferAttribute(new Float32Array(progress), 1))
    this.lines.geometry.setAttribute('aRoute',
      new THREE.BufferAttribute(new Float32Array(routeIdx), 1))
    this.totalRoutes = routes.length
    this.material.uniforms.uMaxRoutes.value = Math.floor(this.totalRoutes * this.density)
    this.hasData = positions.length > 0
    this.setVisible(this.wanted)
  }

  /** Density 0.05..1: fraction of routes shown. */
  setDensity(fraction: number): void {
    this.density = Math.min(1, Math.max(0.05, fraction))
    this.material.uniforms.uMaxRoutes.value =
      Math.max(1, Math.floor(this.totalRoutes * this.density))
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.lines.visible = v && this.hasData
  }

  update(seconds: number): void { this.material.uniforms.uTime.value = seconds }

  dispose(): void {
    this.lines.geometry.dispose()
    this.material.dispose()
  }
}
