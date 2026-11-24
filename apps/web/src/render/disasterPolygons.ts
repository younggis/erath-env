/** GDACS impact polygons drawn as glowing boundaries with alert badges. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'

export interface DisasterPolygon {
  event_id: string
  event_type: string
  event_class: string
  name: string
  alert_level: string
  alert_color: string
  description: string
  report_url: string
  rings: number[][][]
  received_at?: string
}

const BADGE_VERT = /* glsl */`
in vec3 aColor;
out vec3 vColor;
void main(){
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = 10.0;
}`

const BADGE_FRAG = /* glsl */`
precision highp float;
in vec3 vColor;
out vec4 f;
void main(){
  float d = length(gl_PointCoord * 2.0 - 1.0);
  if (d > 1.0) discard;
  float ring = smoothstep(0.55, 0.75, d) * (1.0 - smoothstep(0.9, 1.0, d));
  float core = 1.0 - smoothstep(0.0, 0.45, d);
  f = vec4(vColor * (0.8 + 0.6 * ring), 0.45 * core + 0.9 * ring);
}`

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const num = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16)
  return [((num >> 16) & 255) / 255, ((num >> 8) & 255) / 255, (num & 255) / 255]
}

export class DisasterPolygonLayer {
  readonly lines: THREE.LineSegments
  readonly badges: THREE.Points
  private lineMat: THREE.LineBasicMaterial
  private badgeMat: THREE.ShaderMaterial

  constructor() {
    const lineGeo = new THREE.BufferGeometry()
    lineGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    lineGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(0), 3))
    this.lineMat = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.85, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.lines = new THREE.LineSegments(lineGeo, this.lineMat)
    this.lines.renderOrder = 5
    this.lines.frustumCulled = false
    this.lines.visible = false

    const badgeGeo = new THREE.BufferGeometry()
    badgeGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    badgeGeo.setAttribute('aColor', new THREE.BufferAttribute(new Float32Array(0), 3))
    this.badgeMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: BADGE_VERT, fragmentShader: BADGE_FRAG,
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.badges = new THREE.Points(badgeGeo, this.badgeMat)
    this.badges.renderOrder = 6
    this.badges.frustumCulled = false
    this.badges.visible = false
  }

  setPolygons(polygons: DisasterPolygon[]): void {
    const positions: number[] = []
    const colors: number[] = []
    const badgePos: number[] = []
    const badgeColor: number[] = []
    for (const poly of polygons) {
      const [r, g, b] = hexToRgb(poly.alert_color || '#ff4d5e')
      for (const ring of poly.rings || []) {
        for (let i = 1; i < ring.length; i++) {
          const a = ll2xyz(ring[i - 1][0], ring[i - 1][1], GLOBE_R * 1.02)
          const c = ll2xyz(ring[i][0], ring[i][1], GLOBE_R * 1.02)
          positions.push(a.x, a.y, a.z, c.x, c.y, c.z)
          colors.push(r, g, b, r, g, b)
        }
        if (ring.length) {
          const p = ll2xyz(ring[0][0], ring[0][1], GLOBE_R * 1.035)
          badgePos.push(p.x, p.y, p.z)
          badgeColor.push(r, g, b)
        }
      }
    }
    this.lines.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3))
    this.lines.geometry.setAttribute('color',
      new THREE.BufferAttribute(new Float32Array(colors), 3))
    this.badges.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(badgePos), 3))
    this.badges.geometry.setAttribute('aColor',
      new THREE.BufferAttribute(new Float32Array(badgeColor), 3))
    this.lines.visible = positions.length > 0
    this.badges.visible = badgePos.length > 0
  }

  setVisible(v: boolean): void {
    this.lines.visible = v && this.lines.geometry.getAttribute('position').count > 0
    this.badges.visible = v && this.badges.geometry.getAttribute('position').count > 0
  }

  dispose(): void {
    this.lines.geometry.dispose(); this.lineMat.dispose()
    this.badges.geometry.dispose(); this.badgeMat.dispose()
  }
}
