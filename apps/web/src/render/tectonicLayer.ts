/** Glowing tectonic plate boundaries with travelling lava pulse. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'
import { resampleLine } from './cableGeometry'
import { boundaryRadius, classifyBoundary } from './tectonics'

const VERT = /* glsl */`
in float aKind;
in float aPhase;
uniform float uTime;
out vec3 vColor;
out float vPulse;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  float travel = 0.5 + 0.5 * sin(aPhase * 22.0 - uTime * 2.4);
  float breath = 0.62 + 0.38 * sin(uTime * 0.85);
  vec3 ridge = vec3(1.0, 0.56, 0.12);
  vec3 subduction = vec3(1.0, 0.20, 0.07);
  vec3 transform = vec3(0.88, 0.32, 0.16);
  vColor = aKind < 0.5 ? ridge : (aKind < 1.5 ? subduction : transform);
  vPulse = (0.30 + 0.70 * travel) * breath;
}`

const FRAG = /* glsl */`
precision highp float;
in vec3 vColor;
in float vPulse;
out vec4 f;
void main(){
  f = vec4(vColor * (0.55 + 0.9 * vPulse), min(1.0, 0.28 + 0.72 * vPulse));
}`

const KIND_INDEX = { ridge: 0, subduction: 1, transform: 2 } as const

interface BoundaryFeature {
  properties?: Record<string, any>
  geometry?: { type?: string; coordinates?: any }
}

export class TectonicLayer {
  readonly lines: THREE.LineSegments
  private material: THREE.ShaderMaterial
  private wanted = false
  private hasData = false

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    geo.setAttribute('aKind', new THREE.BufferAttribute(new Float32Array(0), 1))
    geo.setAttribute('aPhase', new THREE.BufferAttribute(new Float32Array(0), 1))
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 } },
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.lines = new THREE.LineSegments(geo, this.material)
    this.lines.renderOrder = 4
    this.lines.frustumCulled = false
    this.lines.visible = false
  }

  setData(features: BoundaryFeature[]): void {
    const positions: number[] = []
    const kinds: number[] = []
    const phases: number[] = []
    const radius = boundaryRadius(GLOBE_R)
    for (const feature of features) {
      if (feature.geometry?.type !== 'LineString') continue
      const coords = feature.geometry.coordinates
      if (!Array.isArray(coords)) continue
      const kind = KIND_INDEX[classifyBoundary(feature.properties || {})]
      const pts = resampleLine(coords, 1.2)
      for (let i = 1; i < pts.length; i++) {
        const a = ll2xyz(pts[i - 1].lon, pts[i - 1].lat, radius)
        const b = ll2xyz(pts[i].lon, pts[i].lat, radius)
        positions.push(a.x, a.y, a.z, b.x, b.y, b.z)
        const phaseA = (i - 1) / Math.max(1, pts.length - 1)
        const phaseB = i / Math.max(1, pts.length - 1)
        kinds.push(kind, kind)
        phases.push(phaseA, phaseB)
      }
    }
    this.lines.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3))
    this.lines.geometry.setAttribute('aKind',
      new THREE.BufferAttribute(new Float32Array(kinds), 1))
    this.lines.geometry.setAttribute('aPhase',
      new THREE.BufferAttribute(new Float32Array(phases), 1))
    this.hasData = positions.length > 0
    this.setVisible(this.wanted)
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
