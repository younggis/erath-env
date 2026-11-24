/** OpenAQ ground stations, coloured by PM2.5-derived AQI. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'

const VERT = /* glsl */`
in vec3 aColor;
out vec3 vColor;
void main(){
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = 8.0;
}`

const FRAG = /* glsl */`
precision highp float;
in vec3 vColor;
out vec4 f;
void main(){
  float d = length(gl_PointCoord * 2.0 - 1.0);
  if (d > 1.0) discard;
  float core = 1.0 - smoothstep(0.0, 0.5, d);
  float ring = smoothstep(0.55, 0.72, d) * (1.0 - smoothstep(0.88, 1.0, d));
  f = vec4(vColor * (0.7 + 0.5 * ring), 0.55 * core + 0.9 * ring);
}`

export interface AirStation {
  station_id: string
  lon: number
  lat: number
  observed_at: string
  values: Record<string, number | null | string>
}

/** US EPA AQI colour scale. */
export function aqiColor(aqi: number | null | undefined): [number, number, number] {
  if (aqi === null || aqi === undefined || !Number.isFinite(aqi)) return [0.45, 0.55, 0.65]
  if (aqi <= 50) return [0.25, 0.85, 0.45]
  if (aqi <= 100) return [0.95, 0.85, 0.25]
  if (aqi <= 150) return [1.0, 0.55, 0.2]
  if (aqi <= 200) return [0.95, 0.25, 0.25]
  if (aqi <= 300) return [0.72, 0.3, 0.85]
  return [0.5, 0.15, 0.25]
}

export class AirQualityLayer {
  readonly points: THREE.Points
  private material: THREE.ShaderMaterial

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    geo.setAttribute('aColor', new THREE.BufferAttribute(new Float32Array(0), 3))
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

  setStations(stations: AirStation[]): void {
    const positions = new Float32Array(stations.length * 3)
    const colors = new Float32Array(stations.length * 3)
    stations.forEach((s, i) => {
      const p = ll2xyz(s.lon, s.lat, GLOBE_R * 1.022)
      positions[i * 3] = p.x; positions[i * 3 + 1] = p.y; positions[i * 3 + 2] = p.z
      const [r, g, b] = aqiColor(s.values?.aqi_pm25 as number | undefined)
      colors[i * 3] = r; colors[i * 3 + 1] = g; colors[i * 3 + 2] = b
    })
    this.points.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    this.points.geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
  }

  setVisible(v: boolean): void { this.points.visible = v }

  dispose(): void {
    this.points.geometry.dispose()
    this.material.dispose()
  }
}
