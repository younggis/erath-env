/** Graded glowing river / lake centreline network (Natural Earth 1:50m). */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'

export interface RiverProperties {
  scalerank: number
  strokeweig: number
  featurecla: string
  name: string | null
}
export interface RiverFeature {
  type: 'Feature'
  geometry: { type: 'LineString'; coordinates: number[][] }
           | { type: 'MultiLineString'; coordinates: number[][][] }
  properties: RiverProperties
}
export interface RiversData { type: string; features: RiverFeature[] }

const RANK_COLORS: Array<[number, number, number]> = [
  [0.70, 0.98, 1.00], // 1 — major trunk rivers, almost white-cyan
  [0.42, 0.88, 1.00], // 2
  [0.25, 0.72, 1.00], // 3
  [0.18, 0.56, 0.96], // 4
  [0.14, 0.44, 0.90], // 5
  [0.12, 0.36, 0.82], // 6+ — tributaries
]

/** Brighter cyan for higher-ranked rivers. */
export function riverColor(rank: number): [number, number, number] {
  return RANK_COLORS[Math.min(RANK_COLORS.length - 1, Math.max(0, rank - 1))]
}

/** Combined rank + Natural Earth line-weight -> emissive strength (0..1). */
export function riverStrength(rank: number, weight: number): number {
  const byRank = Math.max(0, Math.min(1, (12 - rank) / 11))
  const byWeight = Math.max(0, Math.min(1, weight / 0.6))
  return Math.max(0, Math.min(1, 0.28 + 0.55 * byRank + 0.17 * byWeight))
}

/** Flatten GeoJSON centreline pairs into vertex arrays at a fixed globe radius. */
export function buildRiverGeometry(data: RiversData): {
  positions: Float32Array
  colors: Float32Array
  strengths: Float32Array
} {
  const positions: number[] = []
  const colors: number[] = []
  const strengths: number[] = []
  const radius = GLOBE_R * 1.002
  for (const f of data.features) {
    const { scalerank, strokeweig } = f.properties
    const col = riverColor(scalerank)
    const strength = riverStrength(scalerank, strokeweig)
    const lines = f.geometry.type === 'LineString'
      ? [f.geometry.coordinates]
      : f.geometry.coordinates
    for (const line of lines) {
      for (let i = 1; i < line.length; i++) {
        const a = ll2xyz(line[i - 1][0], line[i - 1][1], radius)
        const b = ll2xyz(line[i][0], line[i][1], radius)
        positions.push(a.x, a.y, a.z, b.x, b.y, b.z)
        colors.push(...col, ...col)
        strengths.push(strength, strength)
      }
    }
  }
  return {
    positions: new Float32Array(positions),
    colors: new Float32Array(colors),
    strengths: new Float32Array(strengths),
  }
}

const VERT = /* glsl */`
in vec3 aColor;
in float aStrength;
out vec3 vColor;
out float vStrength;
void main(){
  vColor = aColor;
  vStrength = aStrength;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`

const FRAG = /* glsl */`
precision highp float;
in vec3 vColor;
in float vStrength;
out vec4 f;
void main(){
  f = vec4(vColor * (0.55 + 0.65 * vStrength), 0.28 + 0.62 * vStrength);
}`

export class RiverLayer {
  readonly lines: THREE.LineSegments
  private material: THREE.ShaderMaterial
  private wanted = false

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    geo.setAttribute('aColor', new THREE.BufferAttribute(new Float32Array(0), 3))
    geo.setAttribute('aStrength', new THREE.BufferAttribute(new Float32Array(0), 1))
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.lines = new THREE.LineSegments(geo, this.material)
    this.lines.renderOrder = 2
    this.lines.frustumCulled = false
    this.lines.visible = false
  }

  setData(data: RiversData): void {
    const { positions, colors, strengths } = buildRiverGeometry(data)
    this.lines.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    this.lines.geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
    this.lines.geometry.setAttribute('aStrength', new THREE.BufferAttribute(strengths, 1))
    this.lines.visible = this.wanted && positions.length > 0
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.lines.visible = v && this.lines.geometry.getAttribute('position').count > 0
  }

  dispose(): void {
    this.lines.geometry.dispose()
    this.material.dispose()
  }
}
